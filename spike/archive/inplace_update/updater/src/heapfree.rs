//! `posting_free.bin` (FORMAT_V3 §3.6, R5, R7): heap space of superseded A2b
//! units, and the allocator that reuses it.
//!
//! File: 64-byte header `{u64 magic b"SFUPFL3\0", u32 version 3, u32 0,
//! u64 epoch (offset 16), u64 n_entries (offset 24), zeros, u64 FNV-1a-64 of
//! bytes 0..56 (offset 56)}` — the encoder writes the header with epoch 0 and
//! no entries; the updater rewrites the file (write-new + rename) for e+1
//! before the flip, and trusts it only when its epoch equals the published
//! epoch (else rebuilt by scan, `apply::rebuild_heap_free`). Entry (16 B):
//! `{u64 byte offset in the UNIFIED posting address space (same origin as
//! `list_dir` entries: heap_base + heap offset), u64 length:48 | epoch
//! freed:15 (bits 48..62) | bit 63 reserved}`.
//!
//! Allocator (UPDATER_DESIGN.md revision 2026-09-30): reusable entries =
//! those with `epoch freed <= oldest live reader epoch` (the phase gate has
//! already established oldest >= e_pub, so entries stamped <= e_pub qualify);
//! adjacent reusable entries are coalesced (the merged entry keeps the max
//! epoch), then each unit takes the BEST FIT (smallest sufficient entry,
//! lowest offset on ties); the remainder goes back with the entry's epoch;
//! otherwise the unit is bump-allocated past the published bump pointer.

use std::collections::BTreeMap;

use crate::util::{err, fnv1a64, u32_at, u64_at, Result};

pub const PFREE_MAGIC: u64 = u64::from_le_bytes(*b"SFUPFL3\0");
pub const PFREE_HEADER: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, serde::Serialize)]
pub struct HeapEntry {
    /// Unified byte offset (>= heap_base).
    pub off: u64,
    pub len: u64,
    pub epoch: u64,
}

impl HeapEntry {
    pub fn pack(&self) -> [u8; 16] {
        let mut b = [0u8; 16];
        b[0..8].copy_from_slice(&self.off.to_le_bytes());
        let w = (self.len & 0xFFFF_FFFF_FFFF) | ((self.epoch & 0x7FFF) << 48);
        b[8..16].copy_from_slice(&w.to_le_bytes());
        b
    }
    pub fn unpack(b: &[u8]) -> HeapEntry {
        let w = u64_at(b, 8);
        HeapEntry { off: u64_at(b, 0), len: w & 0xFFFF_FFFF_FFFF, epoch: (w >> 48) & 0x7FFF }
    }
    pub fn end(&self) -> u64 {
        self.off + self.len
    }
}

#[derive(Debug, Clone, Default)]
pub struct HeapFreeList {
    pub epoch: u64,
    pub entries: Vec<HeapEntry>,
}

impl HeapFreeList {
    pub fn serialize(&self) -> Vec<u8> {
        let mut es = self.entries.clone();
        es.sort();
        let mut buf = vec![0u8; PFREE_HEADER + 16 * es.len()];
        buf[0..8].copy_from_slice(&PFREE_MAGIC.to_le_bytes());
        buf[8..12].copy_from_slice(&3u32.to_le_bytes());
        buf[16..24].copy_from_slice(&self.epoch.to_le_bytes());
        buf[24..32].copy_from_slice(&(es.len() as u64).to_le_bytes());
        let ck = fnv1a64(&buf[0..56]);
        buf[56..64].copy_from_slice(&ck.to_le_bytes());
        for (i, e) in es.iter().enumerate() {
            buf[PFREE_HEADER + 16 * i..PFREE_HEADER + 16 * i + 16].copy_from_slice(&e.pack());
        }
        buf
    }

    pub fn parse(buf: &[u8]) -> Result<HeapFreeList> {
        if buf.len() < PFREE_HEADER {
            return err("posting_free.bin too short");
        }
        if u64_at(buf, 0) != PFREE_MAGIC || u32_at(buf, 8) != 3 {
            return err("posting_free.bin bad magic/version");
        }
        if u64_at(buf, 56) != fnv1a64(&buf[0..56]) {
            return err("posting_free.bin header checksum mismatch");
        }
        let epoch = u64_at(buf, 16);
        let n = u64_at(buf, 24) as usize;
        if PFREE_HEADER + 16 * n > buf.len() {
            return err("posting_free.bin entries out of bounds");
        }
        let entries = (0..n).map(|i| HeapEntry::unpack(&buf[PFREE_HEADER + 16 * i..PFREE_HEADER + 16 * i + 16])).collect();
        Ok(HeapFreeList { epoch, entries })
    }

    pub fn free_bytes(&self) -> u64 {
        self.entries.iter().map(|e| e.len).sum()
    }
}

/// Sort by offset and merge adjacent/overlapping entries (max epoch wins).
pub fn coalesce(mut es: Vec<HeapEntry>) -> Vec<HeapEntry> {
    es.sort();
    let mut out: Vec<HeapEntry> = Vec::with_capacity(es.len());
    for e in es {
        if e.len == 0 {
            continue;
        }
        if let Some(l) = out.last_mut() {
            if e.off <= l.end() {
                l.len = l.end().max(e.end()) - l.off;
                l.epoch = l.epoch.max(e.epoch);
                continue;
            }
        }
        out.push(e);
    }
    out
}

/// In-memory allocator over one epoch's writes.
pub struct HeapAlloc {
    /// Reusable entries keyed by (len, off) for best fit.
    pool: BTreeMap<(u64, u64), u64>,
    /// Entries not reusable in this epoch (kept as they are).
    pub held: Vec<HeapEntry>,
    pub bump: u64,
    pub reserve: u64,
    pub heap_base: u64,
    pub reused_bytes: u64,
    pub reused_units: u64,
    pub bumped_bytes: u64,
}

impl HeapAlloc {
    /// `gate` = the epoch every live reader is known to have reached (entries
    /// with epoch <= gate are reusable). `reuse` false keeps every entry held.
    pub fn new(fl: &HeapFreeList, gate: u64, reuse: bool, bump: u64, reserve: u64, heap_base: u64) -> HeapAlloc {
        let (ok, held): (Vec<HeapEntry>, Vec<HeapEntry>) = fl.entries.iter().copied().partition(|e| reuse && e.epoch <= gate);
        let mut pool = BTreeMap::new();
        for e in coalesce(ok) {
            pool.insert((e.len, e.off), e.epoch);
        }
        HeapAlloc { pool, held, bump, reserve, heap_base, reused_bytes: 0, reused_units: 0, bumped_bytes: 0 }
    }

    /// Unified offset for a unit of `size` bytes (8-aligned), or None when the
    /// reserve is exhausted. Nothing is written here.
    pub fn alloc(&mut self, size: u64) -> Option<u64> {
        debug_assert!(size % 8 == 0);
        if let Some((&(len, off), _)) = self.pool.range((size, 0)..).next() {
            let ep = self.pool.remove(&(len, off)).unwrap();
            if len > size {
                self.pool.insert((len - size, off + size), ep);
            }
            self.reused_bytes += size;
            self.reused_units += 1;
            return Some(off);
        }
        if self.bump + size > self.reserve {
            return None;
        }
        let off = self.heap_base + self.bump;
        self.bump += size;
        self.bumped_bytes += size;
        Some(off)
    }

    /// The free list after this epoch: leftover reusable entries + held
    /// entries + the units this epoch superseded (stamped `epoch`).
    pub fn finish(self, superseded: Vec<HeapEntry>, epoch: u64) -> HeapFreeList {
        let mut es: Vec<HeapEntry> = self.pool.into_iter().map(|((len, off), ep)| HeapEntry { off, len, epoch: ep }).collect();
        es.extend(self.held);
        es.extend(superseded);
        HeapFreeList { epoch, entries: coalesce(es) }
    }
}
