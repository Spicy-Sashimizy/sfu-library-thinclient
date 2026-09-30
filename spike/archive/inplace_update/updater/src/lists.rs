//! Active list views (native in `posting_lists.bin` or an A2b unit in
//! `posting_heap.bin`), unit parse/serialise (FORMAT_V3 §3.6 + revision 3:
//! 256-byte header, 24 scalars at 24..216, FNV at 248).

use crate::layout::{pod, walk_one, ListManifest, N_SCALARS};
use crate::store::{Shard, F};
use crate::summary::{decode_summary, RawBlock};
use crate::util::{err, fnv1a64, fnv1a64_cont, u32_at, u64_at, Result};

pub const UNIT_MAGIC: u64 = u64::from_le_bytes(*b"SFUL2B3\0");
pub const UNIT_HEADER: usize = 256;

/// A decoded list (all postings, block offsets, raw summary).
#[derive(Debug, Clone)]
pub struct ListView {
    pub t: usize,
    pub words: Vec<u64>,
    pub bo: Vec<usize>,
    pub blocks: Vec<RawBlock>,
    pub man: ListManifest,
    /// None = native; Some(heap byte offset of the unit header).
    pub unit: Option<u64>,
}

impl ListView {
    pub fn block_of(&self, slot: usize) -> usize {
        match self.bo.binary_search(&slot) {
            Ok(j) => {
                let mut j = j;
                while j + 1 < self.bo.len() && self.bo[j + 1] == slot {
                    j += 1;
                }
                j
            }
            Err(j) => j - 1,
        }
    }
}

/// Parsed unit header.
#[derive(Debug, Clone)]
pub struct UnitHeader {
    pub list: u32,
    pub epoch: u32,
    pub body_bytes: u64,
    pub man: ListManifest,
}

pub fn parse_unit(heap: &[u8], off: usize) -> Result<(UnitHeader, usize)> {
    if off % 8 != 0 || off + UNIT_HEADER > heap.len() {
        return err(format!("unit offset {off} misaligned or out of heap"));
    }
    let h = &heap[off..off + UNIT_HEADER];
    if u64_at(h, 0) != UNIT_MAGIC {
        return err(format!("unit at {off}: bad magic"));
    }
    let body_bytes = u64_at(h, 16) as usize;
    if off + UNIT_HEADER + body_bytes > heap.len() {
        return err(format!("unit at {off}: body beyond heap"));
    }
    let scal: Vec<u64> = (0..N_SCALARS).map(|i| u64_at(h, 24 + 8 * i)).collect();
    let ck = fnv1a64_cont(fnv1a64(&h[0..248]), &heap[off + UNIT_HEADER..off + UNIT_HEADER + body_bytes]);
    if ck != u64_at(h, 248) {
        return err(format!("unit at {off}: checksum mismatch"));
    }
    let man = ListManifest::from_scalars(&scal);
    let loc = walk_one(&man, 0);
    if loc.end != body_bytes {
        return err(format!("unit at {off}: body {body_bytes} B vs layout {} B", loc.end));
    }
    Ok((UnitHeader { list: u32_at(h, 8), epoch: u32_at(h, 12), body_bytes: body_bytes as u64, man }, off + UNIT_HEADER))
}

/// Bytes a unit occupies in the heap: header + body rounded up to 8.
pub fn unit_len(body_bytes: u64) -> u64 {
    UNIT_HEADER as u64 + body_bytes.div_ceil(8) * 8
}

/// Serialise a unit (header + body); body must come from `encode_list`.
pub fn build_unit(list: u32, epoch: u32, man: &ListManifest, body: &[u8]) -> Vec<u8> {
    let mut h = vec![0u8; UNIT_HEADER];
    h[0..8].copy_from_slice(&UNIT_MAGIC.to_le_bytes());
    h[8..12].copy_from_slice(&list.to_le_bytes());
    h[12..16].copy_from_slice(&epoch.to_le_bytes());
    h[16..24].copy_from_slice(&(body.len() as u64).to_le_bytes());
    for (i, s) in man.to_scalars().iter().enumerate() {
        h[24 + 8 * i..32 + 8 * i].copy_from_slice(&s.to_le_bytes());
    }
    let ck = fnv1a64_cont(fnv1a64(&h[0..248]), body);
    h[248..256].copy_from_slice(&ck.to_le_bytes());
    let mut out = h;
    out.extend_from_slice(body);
    while out.len() % 8 != 0 {
        out.push(0);
    }
    out
}

impl Shard {
    /// Active view of list t in `bank` (words loaded atomically for native
    /// lists). `with_summary` decodes the summary too.
    pub fn view(&self, t: usize, bank: usize, with_summary: bool) -> Result<ListView> {
        let entry = self.dir_entry(bank, t);
        if entry == self.native_off(t) {
            let n = self.list_len(t);
            let words: Vec<u64> = (0..n).map(|i| self.word(t, i)).collect();
            let bo = self.block_offsets(t).to_vec();
            let blocks = if with_summary { decode_summary(self.pl(), &self.locs[t], &self.lists[t]) } else { Vec::new() };
            return Ok(ListView { t, words, bo, blocks, man: self.lists[t].clone(), unit: None });
        }
        if entry < self.heap_base {
            return err(format!("list {t}: dir entry {entry} is neither native nor in the heap"));
        }
        let off = (entry - self.heap_base) as usize;
        let heap = self.bytes(F::Heap);
        let (uh, body) = parse_unit(heap, off)?;
        if uh.list as usize != t {
            return err(format!("unit at {off} names list {} not {t}", uh.list));
        }
        let loc = walk_one(&uh.man, body);
        let words: Vec<u64> = pod::<u64>(heap, loc.pp, uh.man.packed_postings_words).to_vec();
        let bo = pod::<usize>(heap, loc.bo, uh.man.block_offsets_len).to_vec();
        let blocks = if with_summary { decode_summary(heap, &loc, &uh.man) } else { Vec::new() };
        Ok(ListView { t, words, bo, blocks, man: uh.man, unit: Some(off as u64) })
    }
}
