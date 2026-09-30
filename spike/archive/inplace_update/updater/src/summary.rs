//! Block summaries: decode the on-disk QuantizedSummary of one list into raw
//! per-block entries, and re-encode raw blocks exactly as
//! `QuantizedSummary::from` + `write_mmap_index` do (toolkit EF/BitField).

use toolkit::{BitField, EliasFano};

use crate::layout::{extend_pod, pod, ListLoc, ListManifest};
use crate::util::get_bits;

/// One block's summary in raw (quantised) form: components ascending, one u8
/// code each, plus the block's (minimum, quant).
#[derive(Debug, Clone, PartialEq)]
pub struct RawBlock {
    pub comps: Vec<u16>,
    pub codes: Vec<u8>,
    pub min: f32,
    pub quant: f32,
}

impl RawBlock {
    /// Dequantised value of entry i (`code * quant + min`, the engine's order
    /// of operations).
    #[inline]
    pub fn value(&self, i: usize) -> f32 {
        self.codes[i] as f32 * self.quant + self.min
    }

    /// Dequantised value of component c, if present.
    pub fn get(&self, c: u16) -> Option<f32> {
        self.comps.binary_search(&c).ok().map(|i| self.value(i))
    }

    /// Summary dot with a sparse vector (components ascending).
    pub fn dot(&self, comps: &[u16], vals: &[f32]) -> f32 {
        let (mut i, mut j) = (0, 0);
        let mut acc = 0f32;
        while i < self.comps.len() && j < comps.len() {
            match self.comps[i].cmp(&comps[j]) {
                std::cmp::Ordering::Equal => {
                    acc += self.value(i) * vals[j];
                    i += 1;
                    j += 1;
                }
                std::cmp::Ordering::Less => i += 1,
                std::cmp::Ordering::Greater => j += 1,
            }
        }
        acc
    }
}

/// Positions of the first `n` set bits (LSB-first) of `words`.
fn ones_positions(words: &[u64], n_bits: usize, n: usize) -> Vec<usize> {
    let mut out = Vec::with_capacity(n);
    for (wi, &w0) in words.iter().enumerate() {
        let mut w = w0;
        while w != 0 && out.len() < n {
            let b = w.trailing_zeros() as usize;
            let pos = wi * 64 + b;
            if pos >= n_bits {
                return out;
            }
            out.push(pos);
            w &= w - 1;
        }
        if out.len() >= n {
            break;
        }
    }
    out
}

/// Elias-Fano select for all k (the reader's `select`).
fn ef_all(bytes: &[u8], loc: &ListLoc, m: &ListManifest) -> Vec<usize> {
    let nv = m.ef_num_vals;
    let hb: &[u64] = pod(bytes, loc.hb, m.ef_high_bits_n_words);
    let lb: &[u64] = pod(bytes, loc.lb, m.ef_low_bits_n_words);
    let ones = ones_positions(hb, m.ef_high_bits_n_bits, nv);
    assert_eq!(ones.len(), nv, "EF high bits: fewer ones than num_vals");
    let w = m.ef_low_bits_field_width as usize;
    (0..nv)
        .map(|k| ((ones[k] - k) << m.ef_low_len) | get_bits(lb, k * w, w) as usize)
        .collect()
}

/// Decode list `m`'s summary (bytes/loc from the same origin) into raw blocks.
pub fn decode_summary(bytes: &[u8], loc: &ListLoc, m: &ListManifest) -> Vec<RawBlock> {
    let nb = m.n_summaries;
    let mins: &[f32] = pod(bytes, loc.mins, m.minimums_len);
    let quants: &[f32] = pod(bytes, loc.quants, m.quants_len);
    let mut blocks: Vec<RawBlock> = (0..nb)
        .map(|b| RawBlock { comps: Vec::new(), codes: Vec::new(), min: mins[b], quant: quants[b] })
        .collect();
    if nb == 0 {
        return blocks;
    }
    let sel = ef_all(bytes, loc, m);
    let sids: &[u64] = pod(bytes, loc.sids, m.summaries_ids_n_words);
    let sw = m.summaries_ids_field_width as usize;
    let values = &bytes[loc.values..loc.values + m.values_len];
    let mut visit = |c: u16, a: usize, b: usize| {
        for p in a..b {
            let blk = get_bits(sids, p * sw, sw) as usize;
            blocks[blk].comps.push(c);
            blocks[blk].codes.push(values[p]);
        }
    };
    if m.has_component_ids {
        let cids: &[u16] = pod(bytes, loc.cids, m.component_ids_len);
        for i in 0..cids.len() {
            visit(cids[i], sel[i], sel[i + 1]);
        }
    } else {
        for c in 0..m.dim {
            let a = sel[c] - c;
            let b = sel[c + 1] - (c + 1);
            if b > a {
                visit(c as u16, a, b);
            }
        }
    }
    blocks
}

/// The build's `utils::quantize` (min, (max-min)/255, round), verbatim
/// arithmetic.
pub fn quantize(values: &[f32]) -> (f32, f32, Vec<u8>) {
    assert!(!values.is_empty());
    let mut mn = values[0];
    let mut mx = values[0];
    for &v in values {
        if v.total_cmp(&mn).is_lt() {
            mn = v;
        }
        if v.total_cmp(&mx).is_gt() {
            mx = v;
        }
    }
    let quant = (mx - mn) / (u8::MAX as f32);
    let codes = values.iter().map(|&v| ((v - mn) / quant).round() as u8).collect();
    (mn, quant, codes)
}

/// The build's `energy_preserving_summary`: component-wise max over the
/// member vectors, sort by value descending, keep the prefix until the
/// running sum reaches `fraction` of the total (inclusive of the crossing
/// element), re-sort by component. Values are f32.
pub fn energy_summary(members: &[(&[u16], &[f32])], fraction: f32) -> (Vec<u16>, Vec<f32>) {
    let mut acc: std::collections::HashMap<u16, f32> = std::collections::HashMap::new();
    for (c, v) in members {
        for (&ci, &vi) in c.iter().zip(v.iter()) {
            acc.entry(ci).and_modify(|h| if *h < vi { *h = vi }).or_insert(vi);
        }
    }
    let mut cv: Vec<(u16, f32)> = acc.into_iter().collect();
    cv.sort_unstable_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    let total: f32 = cv.iter().map(|x| x.1).sum();
    let until = total * fraction;
    let mut s = 0f32;
    let mut kept = Vec::new();
    for x in cv {
        s += x.1;
        kept.push(x);
        if !(s < until) {
            break;
        }
    }
    kept.sort_unstable_by_key(|x| x.0);
    kept.into_iter().unzip()
}

/// A block built from f32 summary values (the build's quantisation).
pub fn raw_from_values(comps: Vec<u16>, vals: &[f32]) -> RawBlock {
    let (min, quant, codes) = quantize(vals);
    RawBlock { comps, codes, min, quant }
}

fn estimate_sparse_space(num_components: usize, max_offset: usize) -> usize {
    num_components * std::mem::size_of::<u16>() * 8 + EliasFano::estimate_space_bits(max_offset + 1, num_components)
}

fn estimate_dense_space(d: usize, max_offset: usize) -> usize {
    EliasFano::estimate_space_bits(max_offset + 1 + d, d)
}

/// Serialise one list (packed words, block offsets, raw summary) as the
/// native slice sequence; returns (body bytes, manifest scalars). Alignment is
/// relative to the start of the returned buffer, which the caller must place
/// at an 8-aligned address. Mirrors `QuantizedSummary::from` exactly.
pub fn encode_list(words: &[u64], block_offsets: &[usize], blocks: &[RawBlock], dim: usize) -> (Vec<u8>, ListManifest) {
    let mut inverted: std::collections::BTreeMap<u16, Vec<(u8, usize)>> = Default::default();
    let mut minimums = Vec::with_capacity(blocks.len());
    let mut quants = Vec::with_capacity(blocks.len());
    for (b, blk) in blocks.iter().enumerate() {
        minimums.push(blk.min);
        quants.push(blk.quant);
        for (&c, &code) in blk.comps.iter().zip(blk.codes.iter()) {
            inverted.entry(c).or_default().push((code, b));
        }
    }
    let num_nonempty = inverted.len();
    let total: usize = inverted.values().map(|v| v.len()).sum();
    let use_sparse = estimate_sparse_space(num_nonempty, total) < estimate_dense_space(dim, dim + total);
    let mut sids: Vec<u64> = Vec::with_capacity(total);
    let mut codes: Vec<u8> = Vec::with_capacity(total);
    let (component_ids, offsets): (Option<Vec<u16>>, Vec<usize>) = if use_sparse {
        let mut cids = Vec::with_capacity(num_nonempty);
        let mut offs = Vec::with_capacity(num_nonempty + 1);
        offs.push(0);
        for (c, ip) in inverted.iter() {
            codes.extend(ip.iter().map(|x| x.0));
            sids.extend(ip.iter().map(|x| x.1 as u64));
            cids.push(*c);
            offs.push(sids.len());
        }
        (Some(cids), offs)
    } else {
        let mut offs = Vec::with_capacity(dim + 1);
        let mut cur = 0usize;
        let mut next = 0usize;
        for (c, ip) in inverted.iter() {
            let comp = *c as usize;
            while next < comp {
                offs.push(cur);
                next += 1;
            }
            offs.push(cur);
            next = comp + 1;
            codes.extend(ip.iter().map(|x| x.0));
            sids.extend(ip.iter().map(|x| x.1 as u64));
            cur = sids.len();
        }
        while next <= dim {
            offs.push(cur);
            next += 1;
        }
        for (i, o) in offs.iter_mut().enumerate() {
            *o += i;
        }
        (None, offs)
    };
    let ef = EliasFano::from(&offsets);
    let sids_bf = BitField::from(sids);

    let mut buf: Vec<u8> = Vec::new();
    extend_pod(&mut buf, words);
    extend_pod(&mut buf, block_offsets);
    let high = ef.high_bits();
    let hbv = high.bv();
    let hw: &[u64] = hbv.words();
    extend_pod(&mut buf, hw);
    let inv = high.ones_inventories();
    extend_pod(&mut buf, inv.block_inventory());
    extend_pod(&mut buf, inv.subblock_inventory());
    extend_pod(&mut buf, inv.overflow_positions());
    let low = ef.low_bits();
    let lw: &[u64] = low.bitvector().words();
    extend_pod(&mut buf, lw);
    let sw: &[u64] = sids_bf.bitvector().words();
    extend_pod(&mut buf, sw);
    extend_pod(&mut buf, &codes);
    extend_pod(&mut buf, &minimums);
    extend_pod(&mut buf, &quants);
    if let Some(c) = &component_ids {
        extend_pod(&mut buf, c);
    }
    let m = ListManifest {
        packed_postings_words: words.len(),
        block_offsets_len: block_offsets.len(),
        n_summaries: blocks.len(),
        dim,
        has_component_ids: component_ids.is_some(),
        component_ids_len: component_ids.as_ref().map(|c| c.len()).unwrap_or(0),
        values_len: codes.len(),
        minimums_len: minimums.len(),
        quants_len: quants.len(),
        summaries_ids_field_width: sids_bf.field_width(),
        summaries_ids_n_bits: sids_bf.bitvector().len(),
        summaries_ids_n_words: sw.len(),
        ef_high_bits_n_bits: hbv.len(),
        ef_high_bits_n_words: hw.len(),
        ef_low_bits_field_width: low.field_width(),
        ef_low_bits_n_bits: low.bitvector().len(),
        ef_low_bits_n_words: lw.len(),
        ef_low_len: ef.low_len(),
        ef_universe: ef.universe(),
        ef_num_vals: ef.num_vals(),
        inv_n_sets: inv.n_sets(),
        inv_block_inventory_len: inv.block_inventory().len(),
        inv_subblock_inventory_len: inv.subblock_inventory().len(),
        inv_overflow_positions_len: inv.overflow_positions().len(),
    };
    (buf, m)
}
