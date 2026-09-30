//! Invariants I1–I10 (UPDATER_DESIGN.md §7) over an opened shard, plus the
//! 2026-09-30 additions: I2 bounded by the published tail (§3.R4), tail
//! counters vs `forward_offsets.bin`, I9 for tail rows (override required),
//! I12 `posting_free.bin` (no live unit overlaps a free entry).

use std::collections::{HashMap, HashSet};

use serde::Serialize;

use crate::freelist::class_of;
use crate::heapfree::HeapEntry;
use crate::lists::{parse_unit, unit_len, ListView};
use crate::store::{visible, w_len, w_start, w_tag, Shard, TAG_MAX};
use crate::summary::RawBlock;
use crate::util::Result;

#[derive(Debug, Default, Serialize)]
pub struct VerifyReport {
    pub epoch: u64,
    pub slot_epochs: (Option<u64>, Option<u64>),
    pub bump: u64,
    pub lists_checked: u64,
    pub unit_lists: u64,
    pub visible_postings: u64,
    pub holes: u64,
    pub overridden_rows: u64,
    /// Overrides left on rows without a visible posting (unobservable at E;
    /// cleared by a reader-gated recovery or overwritten on reuse). Info only.
    pub overrides_on_dead_rows: u64,
    pub tail_words: u64,
    pub tail_rows: u64,
    pub tail_visible_postings: u64,
    pub heap_free_entries: u64,
    pub heap_free_bytes: u64,
    pub violations: Vec<String>,
    pub n_violations: u64,
}

impl VerifyReport {
    fn bad(&mut self, m: String) {
        self.n_violations += 1;
        if self.violations.len() < 50 {
            self.violations.push(m);
        }
    }
    pub fn ok(&self) -> bool {
        self.n_violations == 0
    }
}

/// Required inflation code of a doc in a block (§3.2 step 6).
pub fn required_code(blk: &RawBlock, comps: &[u16], vals: &[f32]) -> u8 {
    let mut ratio = 1.0f64;
    for (&c, &w) in comps.iter().zip(vals) {
        if let Some(old) = blk.get(c) {
            if old > 0.0 {
                ratio = ratio.max((w as f64 / old as f64).max(1.0));
            }
        }
    }
    let need = (((ratio - 1.0) * 32.0 * 1e9).round() / 1e9).ceil();
    if need > 254.0 { 255 } else { need as u8 }
}

/// `deep` also decodes every visible posting (I3 weight check, I6, I7).
pub fn verify(sh: &Shard, deep: bool) -> Result<VerifyReport> {
    let mut r = VerifyReport::default();
    let (s0, s1) = sh.slots();
    r.slot_epochs = (s0.map(|s| s.epoch), s1.map(|s| s.epoch));
    let Some(p) = sh.published() else {
        r.bad("I1: no valid header slot".into());
        return Ok(r);
    };
    let e = p.epoch;
    r.epoch = e;
    r.bump = p.bump;
    r.tail_words = p.tail_words;
    r.tail_rows = p.tail_rows;
    if e > TAG_MAX {
        r.bad("I1: epoch > 32767".into());
    }
    if p.tail_words != sh.tail_words || p.tail_rows != sh.tail_rows {
        r.bad("I1: shard's cached tail counters differ from the published slot".into());
    }
    let n_rows = sh.n_docs + p.tail_rows as usize;
    let reachable = sh.fdw + p.tail_words as usize;
    let file_words = sh.fdw + sh.tail.reserve_words as usize;
    {
        let o = sh.offs();
        if p.tail_rows == 0 && p.tail_words != 0 {
            r.bad(format!("TAIL: {} tail words published with 0 tail rows", p.tail_words));
        }
        if o[sh.n_docs] != sh.fdw as u64 {
            r.bad(format!("TAIL: offsets[n_docs] {} != base words {}", o[sh.n_docs], sh.fdw));
        }
        for j in sh.n_docs..n_rows {
            if o[j + 1] <= o[j] || o[j + 1] > reachable as u64 {
                r.bad(format!("TAIL: offsets[{}] = {} not monotone within the published tail (prev {}, end {reachable})", j + 1, o[j + 1], o[j]));
                break;
            }
        }
        if o[n_rows] != reachable as u64 {
            r.bad(format!("TAIL: offsets[n_docs + tail_rows] {} != base + tail words {reachable}", o[n_rows]));
        }
    }
    let bank = (e & 1) as usize;
    let free = match sh.read_free() {
        Ok(f) => f,
        Err(x) => {
            r.bad(format!("I8: free list unreadable: {x}"));
            return Ok(r);
        }
    };
    if free.epoch != e {
        r.bad(format!("I8: free list epoch {} != E {e}", free.epoch));
    }
    let offs = sh.offs();
    let mut hole_rows: HashSet<usize> = HashSet::new();
    for h in &free.holes {
        match sh.row_of_start(h.start as usize) {
            Some(row) if (offs[row + 1] - offs[row]) as usize == h.len as usize => {
                if !hole_rows.insert(row) {
                    r.bad(format!("I8: duplicate hole row {row}"));
                }
            }
            _ => r.bad(format!("I8: hole {:?} is not a row extent", h)),
        }
        if h.epoch as u64 > e {
            r.bad(format!("I8: hole freed at {} > E {e}", h.epoch));
        }
        let _ = class_of(h.len as u32);
    }
    r.holes = hole_rows.len() as u64;
    let mut row_vis: HashMap<usize, u32> = HashMap::new();
    for t in 0..sh.n_lists {
        r.lists_checked += 1;
        let v: ListView = match sh.view(t, bank, deep) {
            Ok(v) => v,
            Err(x) => {
                r.bad(format!("I10: list {t}: {x}"));
                continue;
            }
        };
        if v.unit.is_some() {
            r.unit_lists += 1;
            if let Some(off) = v.unit {
                if off >= p.bump {
                    r.bad(format!("I10: list {t} unit at {off} beyond published bump {}", p.bump));
                }
            }
        }
        if v.words.is_empty() {
            if !v.bo.is_empty() {
                r.bad(format!("I10: list {t} empty with block offsets"));
            }
        } else if v.bo.first() != Some(&0) || v.bo.last() != Some(&v.words.len()) || !v.bo.windows(2).all(|w| w[0] < w[1]) || v.bo.len() != v.man.n_summaries + 1 {
            r.bad(format!("I10: list {t} block offsets inconsistent"));
        }
        let mut seen: HashSet<usize> = HashSet::new();
        let mut best: Option<(f32, usize)> = None;
        for (i, &w) in v.words.iter().enumerate() {
            if w_start(w) + w_len(w) > file_words {
                r.bad(format!("I2: list {t} slot {i} range beyond forward data file"));
                continue;
            }
            if w_tag(w) > e {
                r.bad(format!("I2: list {t} slot {i} tag {} > E {e}", w_tag(w)));
            }
            if !visible(w, e) {
                continue;
            }
            if w_start(w) + w_len(w) > reachable {
                r.bad(format!("I2: list {t} slot {i} visible range {}+{} beyond base + published tail ({reachable})", w_start(w), w_len(w)));
                continue;
            }
            if w_start(w) >= sh.fdw {
                r.tail_visible_postings += 1;
            }
            r.visible_postings += 1;
            let Some(row) = sh.row_of_start(w_start(w)) else {
                r.bad(format!("I3: list {t} slot {i} START {} is not a row start", w_start(w)));
                continue;
            };
            if (offs[row + 1] - offs[row]) as usize != w_len(w) {
                r.bad(format!("I3: list {t} slot {i} LEN {} != row extent", w_len(w)));
            }
            if hole_rows.contains(&row) {
                r.bad(format!("I4: list {t} slot {i} reaches hole row {row}"));
            }
            if !seen.insert(row) {
                r.bad(format!("I5: list {t} reaches row {row} twice"));
            }
            *row_vis.entry(row).or_default() += 1;
            if deep {
                let (c, vals) = sh.decode(w_start(w), w_len(w));
                match c.binary_search(&(t as u16)) {
                    Ok(k) if vals[k] > 0.0 => {
                        let wt = vals[k];
                        if best.map_or(true, |(b, _)| wt < b) {
                            best = Some((wt, i));
                        }
                        if v.unit.is_none() && w_tag(w) > 0 && !v.blocks.is_empty() {
                            let j = v.block_of(i);
                            let need = required_code(&v.blocks[j], &c, &vals);
                            let have = sh.infl(bank, sh.block_base[t] + j);
                            if have < need {
                                r.bad(format!("I7: list {t} block {j} code {have} < required {need}"));
                            }
                        }
                    }
                    _ => r.bad(format!("I3: list {t} slot {i}: record lacks component {t}")),
                }
            }
        }
        if deep {
            let m = sh.list_min(t);
            if ((m >> 48) & TAG_MAX) > e && m >> 63 == 0 {
                r.bad(format!("I6: list {t} list_min stamped > E"));
            }
            match best {
                None => {
                    if m >> 63 != 1 {
                        r.bad(format!("I6: list {t} has no visible slot but list_min is not EMPTY"));
                    }
                }
                Some((w, i)) => {
                    let mw = f32::from_bits((m & 0xFFFF_FFFF) as u32);
                    let ms = ((m >> 32) & 0xFFFF) as usize;
                    if m >> 63 == 1 || mw.to_bits() != w.to_bits() || ms != i {
                        r.bad(format!("I6: list {t} list_min ({mw}, slot {ms}) != recomputed ({w}, slot {i})"));
                    }
                }
            }
        }
    }
    let mut ids: HashMap<u64, usize> = HashMap::new();
    for row in 0..n_rows {
        let o = sh.override_of(row);
        let vis = row_vis.get(&row).copied().unwrap_or(0) > 0;
        let hole = hole_rows.contains(&row);
        if o != 0 {
            r.overridden_rows += 1;
            if !vis {
                r.overrides_on_dead_rows += 1;
            }
        }
        if vis && row >= sh.n_docs && o == 0 {
            r.bad(format!("I9: tail row {row} is visible without an override"));
        }
        if hole || !vis {
            continue;
        }
        if let Some(prev) = ids.insert(sh.ext_id(row), row) {
            r.bad(format!("I9: id W{} on rows {prev} and {row}", sh.ext_id(row)));
        }
    }
    // I12: posting_free.bin
    match sh.read_posting_free() {
        Err(x) => r.bad(format!("I12: posting_free.bin unreadable: {x}")),
        Ok(pf) => {
            if pf.epoch != e {
                r.bad(format!("I12: posting free list epoch {} != E {e}", pf.epoch));
            }
            r.heap_free_entries = pf.entries.len() as u64;
            r.heap_free_bytes = pf.free_bytes();
            let mut es: Vec<HeapEntry> = pf.entries.clone();
            es.sort();
            let heap_end = sh.heap_base + p.bump;
            for (k, x) in es.iter().enumerate() {
                if x.epoch > e {
                    r.bad(format!("I12: free entry at {} freed at {} > E {e}", x.off, x.epoch));
                }
                if x.len == 0 || x.off % 8 != 0 || x.off < sh.heap_base || x.end() > heap_end {
                    r.bad(format!("I12: free entry [{}, {}) outside the published heap [{}, {heap_end}) or misaligned", x.off, x.end(), sh.heap_base));
                }
                if k > 0 && es[k - 1].end() > x.off {
                    r.bad(format!("I12: free entries overlap at {}", x.off));
                }
            }
            let heap = sh.bytes(crate::store::F::Heap);
            for t in 0..sh.n_lists {
                let entry = sh.dir_entry(bank, t);
                if entry == sh.native_off(t) || entry < sh.heap_base {
                    continue;
                }
                let off = (entry - sh.heap_base) as usize;
                let Ok((uh, _)) = parse_unit(heap, off) else { continue };
                let (a, b) = (entry, entry + unit_len(uh.body_bytes));
                let idx = es.partition_point(|x| x.end() <= a);
                if idx < es.len() && es[idx].off < b {
                    r.bad(format!("I12: live unit of list {t} [{a}, {b}) overlaps free entry [{}, {})", es[idx].off, es[idx].end()));
                }
            }
        }
    }
    Ok(r)
}
