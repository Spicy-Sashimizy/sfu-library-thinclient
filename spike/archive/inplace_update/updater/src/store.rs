//! An opened v3 shard directory: read-only views, writable MAP_SHARED
//! mappings of every file a reader maps, the header, and the single write
//! path (every store goes through `Shard::w_*`, which counts, logs and can
//! inject a crash). Writer I/O per UPDATER_DESIGN.md revision U4.

use std::fs::{File, OpenOptions};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};

use memmap2::{Mmap, MmapMut, MmapOptions};
use vectorium::vector::PackedVectorView;
use vectorium::vector_encoder::SparseDataEncoder;
use vectorium::DotVByteFixedU8Encoder;

use crate::freelist::FreeList;
use crate::heapfree::HeapFreeList;
use crate::layout::{walk, ListLoc, ListManifest};
use crate::util::{err, fnv1a64, parse_wid, u32_at, u64_at, Error, Result};

pub const HEADER_MAGIC: u64 = u64::from_le_bytes(*b"SFUIPV3\0");
pub const HEADER_BYTES: usize = 8192;
pub const HEADER_PAGE: usize = 4096;
pub const HEADER_RECORD: usize = 128;
pub const TAG_MAX: u64 = 0x7FFF;
pub const READERS_BYTES: usize = 256 * 64;

pub const FREE_BIT: u64 = 1 << 63;

#[inline]
pub fn w_tag(w: u64) -> u64 {
    (w >> 48) & TAG_MAX
}
#[inline]
pub fn w_free(w: u64) -> bool {
    w >> 63 == 1
}
#[inline]
pub fn w_start(w: u64) -> usize {
    ((w >> 16) & 0xFFFF_FFFF) as usize
}
#[inline]
pub fn w_len(w: u64) -> usize {
    (w & 0xFFFF) as usize
}
/// `visible(w, E) = (TAG <= E) XOR FREE` (FORMAT_V3 §2.2).
#[inline]
pub fn visible(w: u64, e: u64) -> bool {
    (w_tag(w) <= e) != w_free(w)
}
#[inline]
pub fn make_word(start: usize, len: usize, tag: u64, free: bool) -> u64 {
    ((free as u64) << 63) | ((tag & TAG_MAX) << 48) | (((start as u64) & 0xFFFF_FFFF) << 16) | (len as u64 & 0xFFFF)
}

/// Files the updater maps writable (readers map them too).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum F {
    Pl = 0,
    Hdr = 1,
    Infl = 2,
    Dir = 3,
    Ovr = 4,
    Lmin = 5,
    Fwd = 6,
    Heap = 7,
    Readers = 8,
    /// `forward_offsets.bin`: frozen for base rows; the updater writes the
    /// entries of tail rows beyond the published count (FORMAT_V3 §3.R4 / rev. 6).
    Offs = 9,
}
pub const N_FILES: usize = 10;
pub const FILE_NAMES: [&str; N_FILES] = [
    "posting_lists.bin",
    "inplace_header.bin",
    "block_inflation.bin",
    "list_dir.bin",
    "row_id_override.bin",
    "list_min.bin",
    "forward_data.bin",
    "posting_heap.bin",
    "readers.bin",
    "forward_offsets.bin",
];

/// Operation log entry kinds (power-loss replay, logical byte count).
pub const OP_WRITE: u8 = 1;
pub const OP_SYNC: u8 = 2;
pub const OP_NEWFILE: u8 = 3;
pub const OP_RENAME: u8 = 4;
pub const OP_DIRSYNC: u8 = 5;

/// Write accounting + optional op log + crash injection.
pub struct WriteLog {
    pub n_ops: u64,
    pub logical_bytes: u64,
    pub crash_after: Option<u64>,
    pub log: Option<BufWriter<File>>,
    pub order_replace_after_flip: bool,
}

impl WriteLog {
    fn step(&mut self) -> Result<()> {
        if let Some(n) = self.crash_after {
            if self.n_ops >= n {
                return Err(Error::Injected(n));
            }
        }
        self.n_ops += 1;
        Ok(())
    }
    fn rec(&mut self, kind: u8, file: u8, off: u64, name: &[u8], data: &[u8]) -> Result<()> {
        if let Some(w) = self.log.as_mut() {
            let mut h = [0u8; 24];
            h[0] = kind;
            h[1] = file;
            h[2..4].copy_from_slice(&(name.len() as u16).to_le_bytes());
            h[8..16].copy_from_slice(&off.to_le_bytes());
            h[16..24].copy_from_slice(&(data.len() as u64).to_le_bytes());
            w.write_all(&h)?;
            w.write_all(name)?;
            w.write_all(data)?;
        }
        Ok(())
    }
}

pub struct Shard {
    pub dir: PathBuf,
    pub man_bytes: Vec<u8>,
    pub man: serde_json::Value,
    pub man_fnv: u64,
    pub lists: Vec<ListManifest>,
    pub locs: Vec<ListLoc>,
    pub n_docs: usize,
    pub n_lists: usize,
    pub dim: usize,
    pub n_blocks_total: usize,
    pub block_base: Vec<usize>,
    pub fdw: usize,
    pub heap_base: u64,
    pub heap_reserve: u64,
    /// Forward tail (v3.1, FORMAT_V3 rev. 6): base words, reserve words, reserve rows.
    pub tail: TailInfo,
    /// Published tail counters (header fields 64/72), refreshed by `open` and `write_header`.
    pub tail_words: u64,
    pub tail_rows: u64,
    pub alpha: f32,
    maps: Vec<MmapMut>,
    files: Vec<File>,
    dirty: Vec<Option<(usize, usize)>>,
    strings_map: Mmap,
    soffs_map: Mmap,
    pub encoder: DotVByteFixedU8Encoder,
    pub wlog: WriteLog,
}

fn mget(v: &serde_json::Value, k: &str) -> Result<usize> {
    v.get(k).and_then(|x| x.as_u64()).map(|x| x as usize).ok_or_else(|| Error::Msg(format!("manifest field {k} missing")))
}

/// `forward_tail` of the manifest (reserves 0 when the key is absent, rev. 6 D4).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize)]
pub struct TailInfo {
    pub base_words: u64,
    pub reserve_words: u64,
    pub reserve_rows: u64,
}

#[allow(clippy::too_many_arguments)]
pub fn header_record(slot: u32, epoch: u64, n_docs: u64, n_lists: u64, n_blocks: u64, man_fnv: u64, bump: u64, tail_words: u64, tail_rows: u64) -> [u8; HEADER_RECORD] {
    let mut r = [0u8; HEADER_RECORD];
    r[0..8].copy_from_slice(&HEADER_MAGIC.to_le_bytes());
    r[8..12].copy_from_slice(&3u32.to_le_bytes());
    r[12..16].copy_from_slice(&slot.to_le_bytes());
    r[16..24].copy_from_slice(&epoch.to_le_bytes());
    r[24..32].copy_from_slice(&n_docs.to_le_bytes());
    r[32..40].copy_from_slice(&n_lists.to_le_bytes());
    r[40..48].copy_from_slice(&n_blocks.to_le_bytes());
    r[48..56].copy_from_slice(&man_fnv.to_le_bytes());
    r[56..64].copy_from_slice(&bump.to_le_bytes());
    r[64..72].copy_from_slice(&tail_words.to_le_bytes());
    r[72..80].copy_from_slice(&tail_rows.to_le_bytes());
    let ck = fnv1a64(&r[0..HEADER_RECORD - 8]);
    r[HEADER_RECORD - 8..].copy_from_slice(&ck.to_le_bytes());
    r
}

/// Parsed header slot.
#[derive(Debug, Clone, Copy)]
pub struct Slot {
    pub epoch: u64,
    pub bump: u64,
    pub tail_words: u64,
    pub tail_rows: u64,
}

impl Shard {
    pub fn open(dir: &Path) -> Result<Shard> {
        let canon = crate::guard::check_writable(dir)?;
        let dir: &Path = &canon;
        let man_bytes = std::fs::read(dir.join("manifest.json"))?;
        let man: serde_json::Value = serde_json::from_slice(&man_bytes)?;
        if man.get("forward_format").and_then(|x| x.as_str()) != Some("dotvbyte_fixedu8") || mget(&man, "forward_format_version")? != 3 {
            return err("not an in-place v3 dir");
        }
        let iv = man.get("inplace_v3").ok_or_else(|| Error::Msg("no inplace_v3".into()))?;
        let lists: Vec<ListManifest> = serde_json::from_value(man["posting_lists"].clone())?;
        let n_docs = mget(&man, "n_docs")?;
        let n_lists = mget(&man, "n_posting_lists")?;
        let fdw = mget(&man, "forward_data_words")?;
        if lists.len() != n_lists {
            return err("posting_lists length != n_posting_lists");
        }
        let dim = lists.iter().map(|l| l.dim).max().unwrap_or(n_lists);
        let locs = walk(&lists);
        let mut block_base = Vec::with_capacity(n_lists + 1);
        block_base.push(0);
        for l in &lists {
            block_base.push(block_base.last().unwrap() + l.n_summaries);
        }
        let n_blocks_total = *block_base.last().unwrap();
        if n_blocks_total != mget(iv, "n_blocks_total")? {
            return err("n_blocks_total mismatch");
        }
        let heap_reserve = iv["a2b_reserved"]["posting_heap"]["reserve_bytes"].as_u64().ok_or_else(|| Error::Msg("heap reserve missing".into()))?;
        let tail = match iv.get("forward_tail") {
            Some(ft) => {
                let t = TailInfo {
                    base_words: ft["base_words"].as_u64().ok_or_else(|| Error::Msg("forward_tail.base_words missing".into()))?,
                    reserve_words: ft["reserve_words"].as_u64().unwrap_or(0),
                    reserve_rows: ft["reserve_rows"].as_u64().unwrap_or(0),
                };
                if t.base_words != fdw as u64 {
                    return err(format!("forward_tail.base_words {} != forward_data_words {fdw}", t.base_words));
                }
                t
            }
            None => TailInfo { base_words: fdw as u64, reserve_words: 0, reserve_rows: 0 },
        };
        let cfg: serde_json::Value = serde_json::from_str(man.get("config_json").and_then(|x| x.as_str()).unwrap_or("{}")).unwrap_or_default();
        let alpha = cfg["summarization"]["EnergyPreserving"]["summary_energy"].as_f64().unwrap_or(0.4) as f32;
        if !dir.join("readers.bin").exists() {
            let f = File::create(dir.join("readers.bin"))?;
            f.set_len(READERS_BYTES as u64)?;
            f.sync_all()?;
            File::open(dir)?.sync_all()?;
        }
        let mut maps = Vec::with_capacity(N_FILES);
        let mut files = Vec::with_capacity(N_FILES);
        for name in FILE_NAMES {
            let f = OpenOptions::new().read(true).write(true).open(dir.join(name))?;
            let m = unsafe { MmapOptions::new().map_mut(&f)? };
            maps.push(m);
            files.push(f);
        }
        let ro = |n: &str| -> Result<Mmap> { Ok(unsafe { Mmap::map(&File::open(dir.join(n))?)? }) };
        let strings_map = ro("document_mapping_strings.bin")?;
        let soffs_map = ro("document_mapping_offsets.bin")?;
        let enc_bytes = std::fs::read(dir.join("forward_encoder.bin"))?;
        let cfgb = bincode::config::standard().with_fixed_int_encoding().with_little_endian();
        let (mut encoder, _): (DotVByteFixedU8Encoder, _) =
            bincode::serde::decode_from_slice(&enc_bytes, cfgb).map_err(|e| Error::Msg(format!("encoder: {e}")))?;
        encoder.set_per_doc_scale(true);
        let heap_base = std::fs::metadata(dir.join("posting_lists.bin"))?.len();
        let s = Shard {
            dir: dir.to_path_buf(),
            man_fnv: fnv1a64(&man_bytes),
            man_bytes,
            man,
            lists,
            locs,
            n_docs,
            n_lists,
            dim,
            n_blocks_total,
            block_base,
            fdw,
            heap_base,
            heap_reserve,
            tail,
            tail_words: 0,
            tail_rows: 0,
            alpha,
            maps,
            files,
            dirty: vec![None; N_FILES],
            strings_map,
            soffs_map,
            encoder,
            wlog: WriteLog { n_ops: 0, logical_bytes: 0, crash_after: None, log: None, order_replace_after_flip: false },
        };
        let checks = [
            (F::Hdr, HEADER_BYTES),
            (F::Infl, 2 * n_blocks_total),
            (F::Dir, 16 * n_lists),
            (F::Ovr, 8 * (n_docs + tail.reserve_rows as usize)),
            (F::Lmin, 8 * n_lists),
            (F::Fwd, 8 * (fdw + tail.reserve_words as usize)),
            (F::Heap, heap_reserve as usize),
            (F::Readers, READERS_BYTES),
            (F::Offs, 8 * (n_docs + 1 + tail.reserve_rows as usize)),
        ];
        for (f, n) in checks {
            if s.maps[f as usize].len() != n {
                return err(format!("{} has {} bytes, expected {n}", FILE_NAMES[f as usize], s.maps[f as usize].len()));
            }
        }
        let p = s.published().ok_or_else(|| Error::Msg("no valid header slot".into()))?;
        let mut s = s;
        s.tail_words = p.tail_words;
        s.tail_rows = p.tail_rows;
        Ok(s)
    }

    /// Rows that exist at the published epoch: base rows + published tail rows.
    pub fn n_rows(&self) -> usize {
        self.n_docs + self.tail_rows as usize
    }
    /// Words of `forward_data.bin` reachable at the published epoch.
    pub fn reachable_words(&self) -> usize {
        self.fdw + self.tail_words as usize
    }

    // ---------------------------------------------------------------- views

    pub fn bytes(&self, f: F) -> &[u8] {
        &self.maps[f as usize]
    }
    pub fn pl(&self) -> &[u8] {
        &self.maps[F::Pl as usize]
    }
    pub fn fwd(&self) -> &[u64] {
        bytemuck::cast_slice(&self.maps[F::Fwd as usize][..])
    }
    /// The whole on-disk offsets array (base + reserve entries; entries beyond
    /// `n_rows()` are unpublished and may hold anything).
    pub fn offs(&self) -> &[u64] {
        bytemuck::cast_slice(&self.maps[F::Offs as usize][..])
    }
    pub fn load_u64(&self, f: F, off: usize) -> u64 {
        let p = unsafe { self.maps[f as usize].as_ptr().add(off) } as *const AtomicU64;
        unsafe { (*p).load(Ordering::Acquire) }
    }
    pub fn load_u8(&self, f: F, off: usize) -> u8 {
        let p = unsafe { self.maps[f as usize].as_ptr().add(off) } as *const AtomicU8;
        unsafe { (*p).load(Ordering::Relaxed) }
    }
    /// Native packed-posting word i of list t.
    pub fn word(&self, t: usize, i: usize) -> u64 {
        self.load_u64(F::Pl, self.locs[t].pp + 8 * i)
    }
    pub fn list_len(&self, t: usize) -> usize {
        self.lists[t].packed_postings_words
    }
    pub fn block_offsets(&self, t: usize) -> &[usize] {
        crate::layout::pod(self.pl(), self.locs[t].bo, self.lists[t].block_offsets_len)
    }
    /// Slab id of a base row (tail rows have no slab string).
    pub fn slab_id(&self, row: usize) -> Option<u64> {
        if row >= self.n_docs {
            return None;
        }
        let so: &[u64] = bytemuck::cast_slice(&self.soffs_map[..]);
        parse_wid(&self.strings_map[so[row] as usize..so[row + 1] as usize])
    }
    pub fn override_of(&self, row: usize) -> u64 {
        self.load_u64(F::Ovr, 8 * row)
    }
    /// External id of a row: the override if set, else the slab.
    pub fn ext_id(&self, row: usize) -> u64 {
        let o = self.override_of(row);
        if o != 0 { o & !FREE_BIT } else { self.slab_id(row).unwrap_or(u64::MAX) }
    }
    /// Row of a forward START (word offset), if it is the start of a row that
    /// exists at the published epoch (base rows and published tail rows).
    pub fn row_of_start(&self, start: usize) -> Option<usize> {
        let n = self.n_rows();
        let o = &self.offs()[..n + 1];
        match o.binary_search(&(start as u64)) {
            Ok(r) if r < n => Some(r),
            _ => None,
        }
    }
    pub fn record(&self, start: usize, len: usize) -> &[u64] {
        &self.fwd()[start..start + len]
    }
    /// Decode a record: (components ascending, dequantised values).
    pub fn decode(&self, start: usize, len: usize) -> (Vec<u16>, Vec<f32>) {
        decode_with(&self.encoder, self.record(start, len))
    }
    /// Weight of component t in the record, or None.
    pub fn weight_in(&self, start: usize, len: usize, t: u16) -> Option<f32> {
        let (c, v) = self.decode(start, len);
        c.binary_search(&t).ok().map(|i| v[i])
    }

    // --------------------------------------------------------------- header

    fn slot(&self, s: usize) -> Option<Slot> {
        let base = s * HEADER_PAGE;
        let mut r = [0u8; HEADER_RECORD];
        for i in 0..HEADER_RECORD / 8 {
            r[8 * i..8 * i + 8].copy_from_slice(&self.load_u64(F::Hdr, base + 8 * i).to_le_bytes());
        }
        let ok = u64_at(&r, 0) == HEADER_MAGIC
            && u32_at(&r, 8) == 3
            && u32_at(&r, 12) as usize == s
            && u64_at(&r, 24) == self.n_docs as u64
            && u64_at(&r, 32) == self.n_lists as u64
            && u64_at(&r, 40) == self.n_blocks_total as u64
            && u64_at(&r, 48) == self.man_fnv
            && u64_at(&r, HEADER_RECORD - 8) == fnv1a64(&r[0..HEADER_RECORD - 8])
            && u64_at(&r, 16) <= TAG_MAX
            && u64_at(&r, 64) <= self.tail.reserve_words
            && u64_at(&r, 72) <= self.tail.reserve_rows;
        if ok { Some(Slot { epoch: u64_at(&r, 16), bump: u64_at(&r, 56), tail_words: u64_at(&r, 64), tail_rows: u64_at(&r, 72) }) } else { None }
    }
    pub fn slots(&self) -> (Option<Slot>, Option<Slot>) {
        (self.slot(0), self.slot(1))
    }
    /// Published state: the valid slot with the larger epoch (tie: slot 0).
    pub fn published(&self) -> Option<Slot> {
        match (self.slot(0), self.slot(1)) {
            (Some(a), Some(b)) => Some(if b.epoch > a.epoch { b } else { a }),
            (Some(a), None) => Some(a),
            (None, Some(b)) => Some(b),
            (None, None) => None,
        }
    }
    pub fn epoch(&self) -> u64 {
        self.published().map(|s| s.epoch).unwrap_or(0)
    }

    // ---------------------------------------------------------------- writes

    fn mark_dirty(&mut self, f: F, off: usize, len: usize) {
        let d = &mut self.dirty[f as usize];
        *d = Some(match *d {
            None => (off, off + len),
            Some((a, b)) => (a.min(off), b.max(off + len)),
        });
    }

    /// Aligned 8-byte atomic store (Release) into a mapped file.
    pub fn w_u64(&mut self, f: F, off: usize, v: u64) -> Result<()> {
        debug_assert!(off % 8 == 0);
        self.wlog.step()?;
        self.wlog.rec(OP_WRITE, f as u8, off as u64, &[], &v.to_le_bytes())?;
        self.wlog.logical_bytes += 8;
        let p = unsafe { self.maps[f as usize].as_mut_ptr().add(off) } as *const AtomicU64;
        unsafe { (*p).store(v, Ordering::Release) };
        self.mark_dirty(f, off, 8);
        Ok(())
    }
    /// 1-byte store.
    pub fn w_u8(&mut self, f: F, off: usize, v: u8) -> Result<()> {
        self.wlog.step()?;
        self.wlog.rec(OP_WRITE, f as u8, off as u64, &[], &[v])?;
        self.wlog.logical_bytes += 1;
        let p = unsafe { self.maps[f as usize].as_mut_ptr().add(off) } as *const AtomicU8;
        unsafe { (*p).store(v, Ordering::Relaxed) };
        self.mark_dirty(f, off, 1);
        Ok(())
    }
    /// Plain copy into a mapped file (only for bytes no reader can reach:
    /// holes, heap past the bump pointer, inactive banks).
    pub fn w_bytes(&mut self, f: F, off: usize, data: &[u8]) -> Result<()> {
        if data.is_empty() {
            return Ok(());
        }
        self.wlog.step()?;
        self.wlog.rec(OP_WRITE, f as u8, off as u64, &[], data)?;
        self.wlog.logical_bytes += data.len() as u64;
        self.maps[f as usize][off..off + data.len()].copy_from_slice(data);
        self.mark_dirty(f, off, data.len());
        Ok(())
    }
    /// msync(MS_SYNC) of the dirty range + fsync.
    pub fn sync(&mut self, f: F) -> Result<()> {
        self.wlog.step()?;
        self.wlog.rec(OP_SYNC, f as u8, 0, &[], &[])?;
        if let Some((a, b)) = self.dirty[f as usize].take() {
            self.maps[f as usize].flush_range(a, b - a)?;
        }
        self.files[f as usize].sync_data()?;
        Ok(())
    }
    /// Header slot record as 16 aligned stores, checksum word last, then sync.
    /// Publishes the epoch, the heap bump pointer and the tail counters together.
    pub fn write_header(&mut self, epoch: u64, bump: u64, tail_words: u64, tail_rows: u64) -> Result<()> {
        if epoch > TAG_MAX {
            return err(format!("refusing to publish epoch {epoch} > 32767 (R4)"));
        }
        if tail_words > self.tail.reserve_words || tail_rows > self.tail.reserve_rows {
            return err(format!("refusing to publish tail counters ({tail_words} words, {tail_rows} rows) beyond the reserve ({:?})", self.tail));
        }
        let slot = (epoch & 1) as usize;
        let r = header_record(slot as u32, epoch, self.n_docs as u64, self.n_lists as u64, self.n_blocks_total as u64, self.man_fnv, bump, tail_words, tail_rows);
        let base = slot * HEADER_PAGE;
        for i in 0..HEADER_RECORD / 8 {
            self.w_u64(F::Hdr, base + 8 * i, u64_at(&r, 8 * i))?;
        }
        std::sync::atomic::fence(Ordering::SeqCst);
        self.sync(F::Hdr)?;
        self.tail_words = tail_words;
        self.tail_rows = tail_rows;
        Ok(())
    }
    /// Write a new non-mapped file (write-new, fsync), rename into place,
    /// fsync the directory.
    pub fn replace_file(&mut self, name: &str, data: &[u8]) -> Result<()> {
        let tmp = format!("{name}.next");
        self.wlog.step()?;
        self.wlog.rec(OP_NEWFILE, 255, 0, tmp.as_bytes(), data)?;
        self.wlog.logical_bytes += data.len() as u64;
        {
            let mut f = File::create(self.dir.join(&tmp))?;
            f.write_all(data)?;
            f.sync_all()?;
        }
        self.wlog.step()?;
        let names = format!("{tmp}\0{name}");
        self.wlog.rec(OP_RENAME, 255, 0, names.as_bytes(), &[])?;
        std::fs::rename(self.dir.join(&tmp), self.dir.join(name))?;
        self.wlog.step()?;
        self.wlog.rec(OP_DIRSYNC, 255, 0, &[], &[])?;
        File::open(&self.dir)?.sync_all()?;
        Ok(())
    }
    pub fn flush_log(&mut self) -> Result<()> {
        if let Some(w) = self.wlog.log.as_mut() {
            w.flush()?;
        }
        Ok(())
    }

    // ------------------------------------------------------------ side files

    pub fn read_free(&self) -> Result<FreeList> {
        FreeList::parse(&std::fs::read(self.dir.join("forward_free.bin"))?)
    }
    pub fn read_posting_free(&self) -> Result<HeapFreeList> {
        HeapFreeList::parse(&std::fs::read(self.dir.join("posting_free.bin"))?)
    }
    pub fn list_min(&self, t: usize) -> u64 {
        self.load_u64(F::Lmin, 8 * t)
    }
    pub fn dir_entry(&self, bank: usize, t: usize) -> u64 {
        self.load_u64(F::Dir, 8 * (bank * self.n_lists + t))
    }
    pub fn native_off(&self, t: usize) -> u64 {
        self.locs[t].pp as u64
    }
    pub fn infl(&self, bank: usize, block: usize) -> u8 {
        self.load_u8(F::Infl, bank * self.n_blocks_total + block)
    }
}

pub fn decode_with(enc: &DotVByteFixedU8Encoder, rec: &[u64]) -> (Vec<u16>, Vec<f32>) {
    let d = enc.decode_vector(PackedVectorView::new(rec));
    (d.components().to_vec(), d.values().to_vec())
}

/// Encode a vector as a dv-v2 record with the shard's encoder.
pub fn encode_with(enc: &DotVByteFixedU8Encoder, comps: &[u16], vals: &[f32]) -> Vec<u64> {
    let mut out: Vec<u64> = Vec::new();
    enc.push_encoded_per_doc(comps, vals, &mut out);
    out
}
