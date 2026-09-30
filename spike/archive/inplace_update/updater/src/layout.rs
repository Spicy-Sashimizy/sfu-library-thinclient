//! `posting_lists.bin` per-list layout (the manifest walk of
//! `seismic_upstream/src/mmap_io.rs::read_posting_lists`) and the 24 scalars of
//! `PostingListManifest`.

use serde::{Deserialize, Serialize};

use crate::util::align_up;

/// One entry of `manifest.json` `posting_lists` (field order = the Rust struct
/// order in mmap_io.rs; the A2b unit header serialises them in this order).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ListManifest {
    pub packed_postings_words: usize,
    pub block_offsets_len: usize,
    pub n_summaries: usize,
    pub dim: usize,
    pub has_component_ids: bool,
    pub component_ids_len: usize,
    pub values_len: usize,
    pub minimums_len: usize,
    pub quants_len: usize,
    pub summaries_ids_field_width: u8,
    pub summaries_ids_n_bits: usize,
    pub summaries_ids_n_words: usize,
    pub ef_high_bits_n_bits: usize,
    pub ef_high_bits_n_words: usize,
    pub ef_low_bits_field_width: u8,
    pub ef_low_bits_n_bits: usize,
    pub ef_low_bits_n_words: usize,
    pub ef_low_len: usize,
    pub ef_universe: usize,
    pub ef_num_vals: usize,
    pub inv_n_sets: usize,
    pub inv_block_inventory_len: usize,
    pub inv_subblock_inventory_len: usize,
    pub inv_overflow_positions_len: usize,
}

pub const N_SCALARS: usize = 24;

impl ListManifest {
    pub fn to_scalars(&self) -> [u64; N_SCALARS] {
        [
            self.packed_postings_words as u64,
            self.block_offsets_len as u64,
            self.n_summaries as u64,
            self.dim as u64,
            self.has_component_ids as u64,
            self.component_ids_len as u64,
            self.values_len as u64,
            self.minimums_len as u64,
            self.quants_len as u64,
            self.summaries_ids_field_width as u64,
            self.summaries_ids_n_bits as u64,
            self.summaries_ids_n_words as u64,
            self.ef_high_bits_n_bits as u64,
            self.ef_high_bits_n_words as u64,
            self.ef_low_bits_field_width as u64,
            self.ef_low_bits_n_bits as u64,
            self.ef_low_bits_n_words as u64,
            self.ef_low_len as u64,
            self.ef_universe as u64,
            self.ef_num_vals as u64,
            self.inv_n_sets as u64,
            self.inv_block_inventory_len as u64,
            self.inv_subblock_inventory_len as u64,
            self.inv_overflow_positions_len as u64,
        ]
    }

    pub fn from_scalars(s: &[u64]) -> Self {
        let u = |i: usize| s[i] as usize;
        ListManifest {
            packed_postings_words: u(0),
            block_offsets_len: u(1),
            n_summaries: u(2),
            dim: u(3),
            has_component_ids: s[4] != 0,
            component_ids_len: u(5),
            values_len: u(6),
            minimums_len: u(7),
            quants_len: u(8),
            summaries_ids_field_width: s[9] as u8,
            summaries_ids_n_bits: u(10),
            summaries_ids_n_words: u(11),
            ef_high_bits_n_bits: u(12),
            ef_high_bits_n_words: u(13),
            ef_low_bits_field_width: s[14] as u8,
            ef_low_bits_n_bits: u(15),
            ef_low_bits_n_words: u(16),
            ef_low_len: u(17),
            ef_universe: u(18),
            ef_num_vals: u(19),
            inv_n_sets: u(20),
            inv_block_inventory_len: u(21),
            inv_subblock_inventory_len: u(22),
            inv_overflow_positions_len: u(23),
        }
    }
}

/// Byte offsets of every slice of one list, relative to the same origin as the
/// `start` passed to [`walk_one`].
#[derive(Debug, Clone, Default)]
pub struct ListLoc {
    pub pp: usize,
    pub bo: usize,
    pub hb: usize,
    pub bi: usize,
    pub sbi: usize,
    pub ov: usize,
    pub lb: usize,
    pub sids: usize,
    pub values: usize,
    pub mins: usize,
    pub quants: usize,
    pub cids: usize,
    pub end: usize,
}

/// Walk one list starting at cursor `cur` with the reader's alignment rules.
pub fn walk_one(p: &ListManifest, mut cur: usize) -> ListLoc {
    let pp = align_up(cur, 8);
    cur = pp + 8 * p.packed_postings_words;
    let bo = align_up(cur, 8);
    cur = bo + 8 * p.block_offsets_len;
    let hb = align_up(cur, 8);
    cur = hb + 8 * p.ef_high_bits_n_words;
    let bi = align_up(cur, 8);
    cur = bi + 8 * p.inv_block_inventory_len;
    let sbi = align_up(cur, 2);
    cur = sbi + 2 * p.inv_subblock_inventory_len;
    let ov = align_up(cur, 8);
    cur = ov + 8 * p.inv_overflow_positions_len;
    let lb = align_up(cur, 8);
    cur = lb + 8 * p.ef_low_bits_n_words;
    let sids = align_up(cur, 8);
    cur = sids + 8 * p.summaries_ids_n_words;
    let values = cur;
    cur = values + p.values_len;
    let mins = align_up(cur, 4);
    cur = mins + 4 * p.minimums_len;
    let quants = align_up(cur, 4);
    cur = quants + 4 * p.quants_len;
    let mut cids = cur;
    if p.has_component_ids {
        cids = align_up(cur, 2);
        cur = cids + 2 * p.component_ids_len;
    }
    ListLoc { pp, bo, hb, bi, sbi, ov, lb, sids, values, mins, quants, cids, end: cur }
}

/// Walk every list of the manifest from offset 0.
pub fn walk(lists: &[ListManifest]) -> Vec<ListLoc> {
    let mut out = Vec::with_capacity(lists.len());
    let mut cur = 0usize;
    for p in lists {
        let l = walk_one(p, cur);
        cur = l.end;
        out.push(l);
    }
    out
}

/// Typed read of a POD slice at byte offset `off` (must be aligned).
pub fn pod<T: bytemuck::Pod>(bytes: &[u8], off: usize, n: usize) -> &[T] {
    let sz = std::mem::size_of::<T>();
    bytemuck::cast_slice(&bytes[off..off + n * sz])
}

/// Append a POD slice to `buf`, zero-padding to T's alignment first
/// (`mmap_io.rs::extend_pod`).
pub fn extend_pod<T: bytemuck::Pod>(buf: &mut Vec<u8>, slice: &[T]) {
    let a = std::mem::align_of::<T>();
    let pad = (a - buf.len() % a) % a;
    buf.extend(std::iter::repeat_n(0u8, pad));
    buf.extend_from_slice(bytemuck::cast_slice(slice));
}
