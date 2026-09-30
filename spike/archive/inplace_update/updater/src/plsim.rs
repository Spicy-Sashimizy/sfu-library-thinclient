//! Power-loss replay (B7 power-loss arm; UPDATER_DESIGN.md revision U5).
//! A recorded apply logs every store/copy (file, offset, bytes), every
//! msync+fsync of a file, every new file (written + fsynced), rename and
//! directory fsync. Renamed side files (`SIDE_FILES`: forward_free.bin and,
//! since 2026-09-30, posting_free.bin) are modelled as whole-file replacements. A crash image at cut c (ops [0, c) issued) is the
//! pristine copy plus:
//!   model "drop":  exactly the writes made durable before c (a write to f is
//!                  durable iff a sync of f follows it before c; a rename iff a
//!                  directory fsync follows it before c);
//!   model "pages": the durable writes plus, for every un-synced 4 KiB page of
//!                  every file, the page as of c with probability 0.5 (seeded);
//!                  an un-synced rename survives with probability 0.5.

use std::collections::{BTreeMap, HashMap};
use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;

use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;

use crate::store::{FILE_NAMES, OP_DIRSYNC, OP_NEWFILE, OP_RENAME, OP_SYNC, OP_WRITE};
use crate::util::{err, Result};

pub const PAGE: u64 = 4096;

#[derive(Debug, Clone)]
pub struct Op {
    pub kind: u8,
    pub file: u8,
    pub off: u64,
    pub name: String,
    pub data: Vec<u8>,
}

pub fn load_ops(path: &Path) -> Result<Vec<Op>> {
    let mut b = Vec::new();
    std::fs::File::open(path)?.read_to_end(&mut b)?;
    let mut ops = Vec::new();
    let mut o = 0;
    while o + 24 <= b.len() {
        let kind = b[o];
        let file = b[o + 1];
        let nl = u16::from_le_bytes([b[o + 2], b[o + 3]]) as usize;
        let off = u64::from_le_bytes(b[o + 8..o + 16].try_into().unwrap());
        let dl = u64::from_le_bytes(b[o + 16..o + 24].try_into().unwrap()) as usize;
        o += 24;
        let name = String::from_utf8_lossy(&b[o..o + nl]).into_owned();
        o += nl;
        let data = b[o..o + dl].to_vec();
        o += dl;
        ops.push(Op { kind, file, off, name, data });
    }
    if o != b.len() {
        return err("op log truncated");
    }
    Ok(ops)
}

/// Side files replaced by write-new + rename (not mapped by readers).
pub const SIDE_FILES: [&str; 2] = ["forward_free.bin", "posting_free.bin"];

/// What a crash image changes relative to pristine: mapped-file byte ranges
/// and the final content of each renamed side file (absent = pristine).
#[derive(Debug, Default)]
pub struct Image {
    pub writes: Vec<(u8, u64, Vec<u8>)>,
    pub side_files: BTreeMap<String, Vec<u8>>,
    pub n_durable: u64,
    pub n_pages_kept: u64,
    pub n_pages_dropped: u64,
}

impl Image {
    /// forward_free.bin replaced (kept for the CLI's report key).
    pub fn free_list_replaced(&self) -> bool {
        self.side_files.contains_key("forward_free.bin")
    }
}

fn write_at(dir: &Path, fid: u8, off: u64, data: &[u8]) -> Result<()> {
    let mut f = OpenOptions::new().write(true).open(dir.join(FILE_NAMES[fid as usize]))?;
    f.seek(SeekFrom::Start(off))?;
    f.write_all(data)?;
    Ok(())
}

/// Build + apply an image in one step (page-model writes carry their file).
pub fn materialize(dir: &Path, ops: &[Op], cut: usize, pages_model: bool, seed: u64) -> Result<(Image, Vec<(u8, u64, u64)>)> {
    let dir_c = crate::guard::check_writable(dir)?;
    let dir: &Path = &dir_c;
    let img = crash_image_full(ops, cut, pages_model, seed);
    let mut touched = Vec::new();
    for (f, off, data) in &img.writes {
        write_at(dir, *f, *off, data)?;
        touched.push((*f, *off, data.len() as u64));
    }
    for (name, content) in &img.side_files {
        std::fs::write(dir.join(name), content)?;
    }
    Ok((img, touched))
}

/// As [`crash_image`] but page-model writes keep their file id.
pub fn crash_image_full(ops: &[Op], cut: usize, pages_model: bool, seed: u64) -> Image {
    let cut = cut.min(ops.len());
    let mut last_sync: HashMap<u8, usize> = HashMap::new();
    let mut last_dirsync: Option<usize> = None;
    for (i, op) in ops[..cut].iter().enumerate() {
        match op.kind {
            OP_SYNC => {
                last_sync.insert(op.file, i);
            }
            OP_DIRSYNC => last_dirsync = Some(i),
            _ => {}
        }
    }
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut img = Image::default();
    let mut pending: BTreeMap<(u8, u64), Vec<(u64, Vec<u8>)>> = BTreeMap::new();
    let mut newfiles: HashMap<String, Vec<u8>> = HashMap::new();
    let mut side_durable: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    let mut side_undurable: BTreeMap<String, Vec<u8>> = BTreeMap::new();
    for (i, op) in ops[..cut].iter().enumerate() {
        match op.kind {
            OP_WRITE => {
                if last_sync.get(&op.file).map_or(false, |&j| j > i) {
                    img.writes.push((op.file, op.off, op.data.clone()));
                    img.n_durable += 1;
                } else if pages_model {
                    let mut off = op.off;
                    let mut d = &op.data[..];
                    while !d.is_empty() {
                        let pg = off / PAGE;
                        let n = (((pg + 1) * PAGE - off) as usize).min(d.len());
                        pending.entry((op.file, pg)).or_default().push((off, d[..n].to_vec()));
                        off += n as u64;
                        d = &d[n..];
                    }
                }
            }
            OP_NEWFILE => {
                newfiles.insert(op.name.clone(), op.data.clone());
            }
            OP_RENAME => {
                let mut it = op.name.split('\0');
                let from = it.next().unwrap_or("").to_string();
                let to = it.next().unwrap_or("");
                if SIDE_FILES.contains(&to) {
                    if let Some(content) = newfiles.get(&from).cloned() {
                        if last_dirsync.map_or(false, |j| j > i) {
                            side_durable.insert(to.to_string(), content);
                            side_undurable.remove(to);
                        } else {
                            side_undurable.insert(to.to_string(), content);
                        }
                    }
                }
            }
            _ => {}
        }
    }
    for ((f, _), ws) in pending {
        if rng.random::<f64>() < 0.5 {
            img.n_pages_kept += 1;
            for (off, d) in ws {
                img.writes.push((f, off, d));
            }
        } else {
            img.n_pages_dropped += 1;
        }
    }
    img.side_files = side_durable;
    if pages_model {
        for (name, u) in side_undurable {
            if rng.random::<f64>() < 0.5 {
                img.side_files.insert(name, u);
            }
        }
    }
    img
}

/// Restore a work copy from pristine over every range any op of the log can
/// touch, plus forward_free.bin.
pub fn restore(work: &Path, pristine: &Path, ops: &[Op]) -> Result<u64> {
    let work_c = crate::guard::check_writable(work)?;
    let work: &Path = &work_c;
    let mut ranges: BTreeMap<u8, Vec<(u64, u64)>> = BTreeMap::new();
    for op in ops {
        if op.kind == OP_WRITE {
            let a = op.off / PAGE * PAGE;
            let b = (op.off + op.data.len() as u64).div_ceil(PAGE) * PAGE;
            ranges.entry(op.file).or_default().push((a, b));
        }
    }
    let mut bytes = 0u64;
    for (fid, mut rs) in ranges {
        rs.sort();
        let mut merged: Vec<(u64, u64)> = Vec::new();
        for (a, b) in rs {
            if let Some(l) = merged.last_mut() {
                if a <= l.1 {
                    l.1 = l.1.max(b);
                    continue;
                }
            }
            merged.push((a, b));
        }
        let name = FILE_NAMES[fid as usize];
        let mut src = std::fs::File::open(pristine.join(name))?;
        let len = src.metadata()?.len();
        let mut dst = OpenOptions::new().write(true).open(work.join(name))?;
        for (a, b) in merged {
            let b = b.min(len);
            if a >= b {
                continue;
            }
            let mut buf = vec![0u8; (b - a) as usize];
            src.seek(SeekFrom::Start(a))?;
            src.read_exact(&mut buf)?;
            dst.seek(SeekFrom::Start(a))?;
            dst.write_all(&buf)?;
            bytes += b - a;
        }
        dst.sync_all()?;
    }
    for name in SIDE_FILES {
        std::fs::copy(pristine.join(name), work.join(name))?;
        let _ = std::fs::remove_file(work.join(format!("{name}.next")));
    }
    Ok(bytes)
}
