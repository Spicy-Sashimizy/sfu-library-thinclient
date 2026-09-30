//! Plan + apply one batch (UPDATER_DESIGN.md §2–§4 and revisions), and the
//! pre-batch recovery (§5, R1/R5). 2026-09-30: `+tail` forward append
//! (FORMAT_V3 §3.R4 / rev. 6) and A2b heap reuse (R7, `heapfree`).

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use rayon::prelude::*;
use serde::Serialize;

use crate::batch::{Rec, OP_DELETE, OP_UPSERT};
use crate::freelist::{FreeList, Hole};
use crate::heapfree::{coalesce, HeapAlloc, HeapEntry, HeapFreeList};
use crate::lists::{build_unit, parse_unit, unit_len, ListView};
use crate::readers::Table;
use crate::store::{decode_with, encode_with, make_word, visible, w_free, w_len, w_start, w_tag, Shard, F, FREE_BIT, TAG_MAX};
use crate::summary::{encode_list, energy_summary, raw_from_values, RawBlock};
use crate::util::{err, Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Arm {
    A2,
    A2TwoPhase { old_at_fill: bool },
    A2b,
    A2bTwoPhase { old_at_fill: bool },
}

impl Arm {
    /// `a2`, `a2b`, `a2-2p-free`, … with an optional `-tail` suffix (the
    /// `+tail` variant of FORMAT_V3 §3.R4). Returns (arm, tail).
    pub fn parse_full(s: &str) -> Result<(Arm, bool)> {
        match s.strip_suffix("-tail") {
            Some(base) => Ok((Arm::parse(base)?, true)),
            None => Ok((Arm::parse(s)?, false)),
        }
    }
    pub fn parse(s: &str) -> Result<Arm> {
        Ok(match s {
            "a2" => Arm::A2,
            "a2-2p-free" => Arm::A2TwoPhase { old_at_fill: false },
            "a2-2p-fill" => Arm::A2TwoPhase { old_at_fill: true },
            "a2b" => Arm::A2b,
            "a2b-2p-free" => Arm::A2bTwoPhase { old_at_fill: false },
            "a2b-2p-fill" => Arm::A2bTwoPhase { old_at_fill: true },
            _ => return err(format!("unknown arm {s}")),
        })
    }
    pub fn name(&self) -> &'static str {
        match self {
            Arm::A2 => "A2",
            Arm::A2TwoPhase { old_at_fill: false } => "A2-2p/old-at-free",
            Arm::A2TwoPhase { old_at_fill: true } => "A2-2p/old-at-fill",
            Arm::A2b => "A2b",
            Arm::A2bTwoPhase { old_at_fill: false } => "A2b-2p/old-at-free",
            Arm::A2bTwoPhase { old_at_fill: true } => "A2b-2p/old-at-fill",
        }
    }
    pub fn two_phase(&self) -> bool {
        matches!(self, Arm::A2TwoPhase { .. } | Arm::A2bTwoPhase { .. })
    }
    pub fn old_at_fill(&self) -> bool {
        matches!(self, Arm::A2TwoPhase { old_at_fill: true } | Arm::A2bTwoPhase { old_at_fill: true })
    }
    pub fn is_a2b(&self) -> bool {
        matches!(self, Arm::A2b | Arm::A2bTwoPhase { .. })
    }
    /// Evictions allowed: A2b always (fresh heap space), A2 only two-phase.
    pub fn evicts(&self) -> bool {
        !matches!(self, Arm::A2)
    }
}

#[derive(Debug, Clone)]
pub struct Opts {
    pub arm: Arm,
    /// `+tail`: records that fit no hole are appended to the forward tail
    /// reserve (FORMAT_V3 §3.R4); without it they are unplaced.
    pub tail: bool,
    /// A2b: reuse heap space of superseded units (R7). Off = bump only.
    pub heap_reuse: bool,
    pub reader_timeout: Duration,
    pub hybrid_min_slots: usize,
    /// Test hook: stop (as if crashed) right after the first flip.
    pub stop_after_first_flip: bool,
    /// Test hook (R5b): replace forward_free.bin AFTER the header flip.
    pub replace_after_flip: bool,
    /// Extra sleep between flips (0 by default; the gap is recorded).
    pub hold_between_flips: Duration,
}

impl Default for Opts {
    fn default() -> Self {
        Opts {
            arm: Arm::A2,
            tail: false,
            heap_reuse: true,
            reader_timeout: Duration::from_secs(600),
            hybrid_min_slots: 0,
            stop_after_first_flip: false,
            replace_after_flip: false,
            hold_between_flips: Duration::ZERO,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct PhaseReport {
    pub epoch: u64,
    pub wait_readers_s: f64,
    pub write_s: f64,
    pub flip_done_at_s: f64,
    pub marks: u64,
    pub fills: u64,
    pub records_written: u64,
    pub units_written: u64,
    pub unit_bytes: u64,
    pub tail_records_written: u64,
    pub heap_reused_units: u64,
    pub heap_reused_bytes: u64,
    pub heap_bumped_bytes: u64,
    pub heap_superseded_bytes: u64,
    pub stale_reader_slots_cleared: u64,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct Report {
    pub arm: String,
    pub safety: String,
    pub writer_io: String,
    pub reuse_gate: String,
    pub start_epoch: u64,
    pub end_epoch: u64,
    pub records_in_batch: u64,
    pub superseded_in_batch: u64,
    pub deletes_offered: u64,
    pub deletes_applied: u64,
    pub deletes_noop: u64,
    pub docs_offered: u64,
    pub docs_updates: u64,
    pub docs_inserts: u64,
    pub docs_placed: u64,
    pub docs_placed_hole: u64,
    pub docs_placed_tail: u64,
    pub docs_unplaced_no_hole: u64,
    pub docs_unplaced_no_posting: u64,
    pub tail: bool,
    pub tail_reserve_words: u64,
    pub tail_reserve_rows: u64,
    pub tail_words_before: u64,
    pub tail_words_after: u64,
    pub tail_rows_before: u64,
    pub tail_rows_after: u64,
    pub oov_components: u64,
    pub postings_offered: u64,
    pub postings_inserted: u64,
    pub postings_dropped_capacity: u64,
    pub postings_dropped_unplaced: u64,
    pub postings_spilled_hybrid: u64,
    pub postings_evicted: u64,
    pub postings_freed: u64,
    pub rows_freed: u64,
    pub rows_fully_evicted: u64,
    pub holes_before: u64,
    pub holes_after: u64,
    pub lists_touched: u64,
    pub lists_decoded_for_eviction: u64,
    pub lists_min_recomputed: u64,
    pub record_decodes: u64,
    pub infl_blocks_raised: u64,
    pub infl_saturated: u64,
    pub infl_code_hist: Vec<u64>,
    pub blind_components: u64,
    pub blind_mass: f64,
    pub a2b_lists_rewritten: u64,
    pub a2b_blocks_recomputed: u64,
    pub a2b_blocks_removed: u64,
    pub heap_bytes_before: u64,
    pub heap_bytes_after: u64,
    pub heap_reserve: u64,
    pub heap_reuse: bool,
    pub heap_reused_units: u64,
    pub heap_reused_bytes: u64,
    pub heap_bumped_bytes: u64,
    pub heap_superseded_bytes: u64,
    pub heap_free_entries_before: u64,
    pub heap_free_bytes_before: u64,
    pub heap_free_entries_after: u64,
    pub heap_free_bytes_after: u64,
    pub inserted_by_len_decile: Vec<u64>,
    pub dropped_by_len_decile: Vec<u64>,
    pub phases: Vec<PhaseReport>,
    pub plan_s: f64,
    pub total_s: f64,
    pub gap_s: f64,
    pub logical_bytes: u64,
    pub write_ops: u64,
    pub recovery: RecoveryReport,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct RecoveryReport {
    pub epoch: u64,
    pub aborted_inserts_neutralised: u64,
    pub aborted_deletes_restored: u64,
    pub overrides_cleared: u64,
    /// Overrides of dead rows left in place because a registered reader still
    /// holds an epoch < E (it may still resolve those rows); cleared by a
    /// later recovery or overwritten by the row's reuse.
    pub overrides_clear_deferred: u64,
    pub free_list_trusted: bool,
    pub free_list_rebuilt: bool,
    pub free_list_holes: u64,
    pub posting_free_trusted: bool,
    pub posting_free_rebuilt: bool,
    pub posting_free_entries: u64,
    pub posting_free_bytes: u64,
    pub list_min_recomputed: u64,
    pub seconds: f64,
}

/// Per-row scan of the active lists at epoch E.
pub struct RowScan {
    pub visible: Vec<u32>,
    pub ever: Vec<bool>,
    pub maxtag: Vec<u16>,
}

pub fn scan_rows(sh: &Shard, bank: usize, e: u64) -> Result<RowScan> {
    let n = sh.n_rows();
    let per: Vec<Result<Vec<(u32, bool, u16)>>> = (0..sh.n_lists)
        .into_par_iter()
        .map(|t| -> Result<Vec<(u32, bool, u16)>> {
            let mut out = Vec::new();
            let nat = sh.dir_entry(bank, t) == sh.native_off(t);
            for i in 0..sh.list_len(t) {
                let w = sh.word(t, i);
                if let Some(r) = sh.row_of_start(w_start(w)) {
                    let vis = nat && visible(w, e);
                    out.push((r as u32, vis, if nat && !vis { w_tag(w) as u16 } else { 0 }));
                }
            }
            if !nat {
                let v = sh.view(t, bank, false)?;
                for &w in &v.words {
                    if let Some(r) = sh.row_of_start(w_start(w)) {
                        if visible(w, e) {
                            out.push((r as u32, true, 0));
                        }
                    }
                }
            }
            Ok(out)
        })
        .collect();
    let mut rs = RowScan { visible: vec![0; n], ever: vec![false; n], maxtag: vec![0; n] };
    for p in per {
        for (r, vis, tag) in p? {
            let r = r as usize;
            rs.ever[r] = true;
            if vis {
                rs.visible[r] += 1;
            } else if tag > rs.maxtag[r] {
                rs.maxtag[r] = tag;
            }
        }
    }
    Ok(rs)
}

fn row_len(sh: &Shard, r: usize) -> usize {
    let o = sh.offs();
    (o[r + 1] - o[r]) as usize
}

/// Minimum over visible slots of list t at epoch e (weight, slot) by decoding
/// every visible posting; returns the list_min word stamped with `stamp`.
fn full_min(sh: &Shard, words: &[u64], t: usize, e: u64, stamp: u64, decodes: &mut u64) -> u64 {
    let mut best: Option<(f32, usize)> = None;
    for (i, &w) in words.iter().enumerate() {
        if !visible(w, e) {
            continue;
        }
        *decodes += 1;
        let wt = sh.weight_in(w_start(w), w_len(w), t as u16).unwrap_or(0.0);
        if best.map_or(true, |(b, _)| wt < b) {
            best = Some((wt, i));
        }
    }
    min_word(best, stamp)
}

fn min_word(best: Option<(f32, usize)>, stamp: u64) -> u64 {
    match best {
        None => FREE_BIT,
        Some((w, i)) => (w.to_bits() as u64) | ((i as u64 & 0xFFFF) << 32) | ((stamp & TAG_MAX) << 48),
    }
}

// ------------------------------------------------------------------ recovery

/// Free heap space by scan: `[heap_base, heap_base + bump)` minus the extents
/// of the units the active bank names, every gap stamped E (the most
/// conservative freed epoch: reusable only once every reader has reached E).
pub fn rebuild_heap_free(sh: &Shard, bank: usize, bump: u64, e: u64) -> Result<HeapFreeList> {
    let heap = sh.bytes(F::Heap);
    let mut live: Vec<(u64, u64)> = Vec::new();
    for t in 0..sh.n_lists {
        let entry = sh.dir_entry(bank, t);
        if entry == sh.native_off(t) {
            continue;
        }
        if entry < sh.heap_base {
            return err(format!("list {t}: dir entry {entry} is neither native nor in the heap"));
        }
        let (uh, _) = parse_unit(heap, (entry - sh.heap_base) as usize)?;
        live.push((entry, entry + unit_len(uh.body_bytes)));
    }
    live.sort_unstable();
    let mut entries = Vec::new();
    let mut cur = sh.heap_base;
    let end = sh.heap_base + bump;
    for (a, b) in live {
        if a > cur {
            entries.push(HeapEntry { off: cur, len: a - cur, epoch: e });
        }
        cur = cur.max(b);
    }
    if end > cur {
        entries.push(HeapEntry { off: cur, len: end - cur, epoch: e });
    }
    Ok(HeapFreeList { epoch: e, entries: coalesce(entries) })
}

/// Pre-batch recovery (R1, R5): neutralise words tagged > E, clear overrides
/// of rows with no visible posting, trust or rebuild the forward free list
/// and the posting free list, recompute list_min entries stamped > E.
pub fn recover(sh: &mut Shard, table: Option<&Table>) -> Result<RecoveryReport> {
    recover_scan(sh, table).map(|x| x.0)
}

/// [`recover`] that also returns the row scan at E (the plan reuses it: a row
/// is live iff it has a visible posting). Override clearing is gated on the
/// reader table (2026-09-30): a row dead at E may still be resolved by a
/// reader registered at an epoch < E, so its override is cleared only when
/// every live reader holds an epoch >= E (or no table is given: tests only).
pub fn recover_scan(sh: &mut Shard, table: Option<&Table>) -> Result<(RecoveryReport, RowScan)> {
    let t0 = Instant::now();
    let pubs = sh.published().ok_or_else(|| Error::Msg("no valid header".into()))?;
    let e = pubs.epoch;
    let bank = (e & 1) as usize;
    let mut rep = RecoveryReport { epoch: e, ..Default::default() };
    let mut fixes: Vec<(usize, u64)> = Vec::new();
    for t in 0..sh.n_lists {
        for i in 0..sh.list_len(t) {
            let w = sh.word(t, i);
            if w_tag(w) > e {
                let nw = if w_free(w) {
                    rep.aborted_deletes_restored += 1;
                    w & 0xFFFF_FFFF_FFFF
                } else {
                    rep.aborted_inserts_neutralised += 1;
                    FREE_BIT | (e << 48) | (w & 0xFFFF_FFFF_FFFF)
                };
                fixes.push((sh.locs[t].pp + 8 * i, nw));
            }
        }
    }
    for (off, w) in &fixes {
        sh.w_u64(F::Pl, *off, *w)?;
    }
    if !fixes.is_empty() {
        sh.sync(F::Pl)?;
    }
    let rs = scan_rows(sh, bank, e)?;
    let mut cleared = 0u64;
    let mut stale = 0u64;
    let may_clear = match table {
        None => true,
        Some(t) => t.oldest(&mut stale).is_none_or(|o| o >= e),
    };
    for r in 0..sh.n_rows() {
        if rs.visible[r] == 0 && sh.override_of(r) != 0 {
            if may_clear {
                sh.w_u64(F::Ovr, 8 * r, 0)?;
                cleared += 1;
            } else {
                rep.overrides_clear_deferred += 1;
            }
        }
    }
    if cleared > 0 {
        sh.sync(F::Ovr)?;
    }
    rep.overrides_cleared = cleared;
    let trusted = match sh.read_free() {
        Ok(fl) if fl.epoch == e => Some(fl),
        _ => None,
    };
    let fl = match trusted {
        Some(fl) => {
            rep.free_list_trusted = true;
            fl
        }
        None => {
            rep.free_list_rebuilt = true;
            let mut holes = Vec::new();
            for r in 0..sh.n_rows() {
                if rs.ever[r] && rs.visible[r] == 0 {
                    let tag = if rs.maxtag[r] > 0 { rs.maxtag[r] as u64 } else { e };
                    holes.push(Hole { start: sh.offs()[r] as u32, len: row_len(sh, r) as u16, epoch: tag.min(e) as u16 });
                }
            }
            let fl = FreeList { epoch: e, holes };
            let bytes = fl.serialize();
            sh.replace_file("forward_free.bin", &bytes)?;
            fl
        }
    };
    rep.free_list_holes = fl.holes.len() as u64;
    let pf = match sh.read_posting_free() {
        Ok(pf) if pf.epoch == e => {
            rep.posting_free_trusted = true;
            pf
        }
        _ => {
            rep.posting_free_rebuilt = true;
            let pf = rebuild_heap_free(sh, bank, pubs.bump, e)?;
            sh.replace_file("posting_free.bin", &pf.serialize())?;
            pf
        }
    };
    rep.posting_free_entries = pf.entries.len() as u64;
    rep.posting_free_bytes = pf.free_bytes();
    let mut lm_fix = Vec::new();
    let mut decodes = 0u64;
    for t in 0..sh.n_lists {
        let m = sh.list_min(t);
        if m >> 63 == 0 && ((m >> 48) & TAG_MAX) > e {
            let v = sh.view(t, bank, false)?;
            lm_fix.push((t, full_min(sh, &v.words, t, e, e, &mut decodes)));
        }
    }
    for (t, m) in &lm_fix {
        sh.w_u64(F::Lmin, 8 * t, *m)?;
    }
    if !lm_fix.is_empty() {
        sh.sync(F::Lmin)?;
    }
    rep.list_min_recomputed = lm_fix.len() as u64;
    rep.seconds = t0.elapsed().as_secs_f64();
    Ok((rep, rs))
}

// ---------------------------------------------------------------------- plan

/// Where a new record goes: a hole (padded to the hole) or the forward tail
/// (`+tail`, appended at the published bump, a new row).
#[derive(Debug, Clone, Copy)]
struct Place {
    start: usize,
    len: usize,
    row: usize,
    hole: Option<Hole>,
}

struct NewDoc {
    id: u64,
    comps: Vec<u16>,
    vals: Vec<f32>,
    rec: Vec<u64>,
    #[allow(dead_code)]
    old_row: Option<usize>,
    place: Option<Place>,
    /// No hole fitted; the record goes to the tail if any posting survives.
    tail_candidate: bool,
    n_inserted: u32,
}

impl NewDoc {
    fn placed(&self) -> bool {
        self.place.is_some() || self.tail_candidate
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum FreePhase {
    P1,
    P2,
}

/// Live id -> row, sorted for binary search. A row is live iff it has a
/// visible posting at E (`scan_rows`), or it is a base row that never had a
/// posting (every component truncated by the list cap) and is not a hole:
/// such a doc is not retrievable but its id stays addressable so a delete
/// or update can free its row. Rows whose postings are all dead (holes,
/// leaked holes, tail rows whose doc is gone) carry no live id.
pub fn id_map(sh: &Shard, rs: &RowScan, holes: &HashSet<u32>) -> Result<Vec<(u64, u32)>> {
    let offs = sh.offs();
    let mut v: Vec<(u64, u32)> = (0..sh.n_rows())
        .into_par_iter()
        .filter(|&r| rs.visible[r] > 0 || (!rs.ever[r] && r < sh.n_docs && !holes.contains(&(offs[r] as u32))))
        .map(|r| (sh.ext_id(r), r as u32))
        .filter(|x| x.0 != u64::MAX)
        .collect();
    v.par_sort_unstable();
    for w in v.windows(2) {
        if w[0].0 == w[1].0 {
            return err(format!("id W{} maps to two live rows {} and {}", w[0].0, w[0].1, w[1].1));
        }
    }
    Ok(v)
}

fn lookup(map: &[(u64, u32)], id: u64) -> Option<usize> {
    map.binary_search_by_key(&id, |x| x.0).ok().map(|i| map[i].1 as usize)
}

/// Wait until every live reader holds an epoch >= `need` (R3 / revision U1-U2).
fn gate(table: &Table, need: u64, timeout: Duration, cleared: &mut u64) -> Result<f64> {
    let t0 = Instant::now();
    loop {
        match table.oldest(cleared) {
            None => return Ok(t0.elapsed().as_secs_f64()),
            Some(o) if o >= need => return Ok(t0.elapsed().as_secs_f64()),
            _ => {}
        }
        if t0.elapsed() > timeout {
            return err(format!("reader table: a reader stayed below epoch {need} for {:?}; batch aborted before its next write", timeout));
        }
        std::thread::sleep(Duration::from_millis(5));
    }
}

/// Copy the active bank into the inactive one, writing only differing runs.
fn copy_bank(sh: &mut Shard, f: F, bank_bytes: usize, from: usize, to: usize) -> Result<()> {
    let src: Vec<u8> = sh.bytes(f)[from * bank_bytes..(from + 1) * bank_bytes].to_vec();
    let dst: Vec<u8> = sh.bytes(f)[to * bank_bytes..(to + 1) * bank_bytes].to_vec();
    let mut i = 0;
    while i < bank_bytes {
        if src[i] != dst[i] {
            let mut j = i;
            while j < bank_bytes && src[j] != dst[j] {
                j += 1;
            }
            let (a, b) = if f == F::Dir { (i / 8 * 8, (j + 7) / 8 * 8) } else { (i, j) };
            if f == F::Dir {
                for k in (a..b).step_by(8) {
                    let v = u64::from_le_bytes(src[k..k + 8].try_into().unwrap());
                    sh.w_u64(f, to * bank_bytes + k, v)?;
                }
            } else {
                sh.w_bytes(f, to * bank_bytes + a, &src[a..b])?;
            }
            i = b;
        } else {
            i += 1;
        }
    }
    Ok(())
}

/// Pad a dv-v2 record to `h` words inside the record: zero words inserted just
/// before the end-anchored u8 values tail (FORMAT_V3 §3.4).
pub fn pad_record(rec: &[u64], h: usize, n_tail_bytes: usize) -> Vec<u64> {
    let n = rec.len();
    if h == n {
        return rec.to_vec();
    }
    let bytes: &[u8] = bytemuck::cast_slice(rec);
    let cut = bytes.len() - n_tail_bytes;
    let mut out: Vec<u8> = Vec::with_capacity(8 * h);
    out.extend_from_slice(&bytes[..cut]);
    out.extend(std::iter::repeat_n(0u8, 8 * (h - n)));
    out.extend_from_slice(&bytes[cut..]);
    out.chunks_exact(8).map(|c| u64::from_le_bytes(c.try_into().unwrap())).collect()
}

/// Bytes of the SIMD values tail of a dv record (n_packs * 8; N = u8::BITS = 8 lanes).
fn tail_bytes(rec: &[u64]) -> usize {
    let bytes: &[u8] = bytemuck::cast_slice(rec);
    let n = u16::from_ne_bytes([bytes[0], bytes[1]]) as usize;
    (n / 8) * 8
}

/// Encode + pad + verify a record into a hole of `h` words.
fn padded_record(sh: &Shard, rec: &[u64], h: usize) -> Result<Vec<u64>> {
    let pr = pad_record(rec, h, tail_bytes(rec));
    let a = decode_with(&sh.encoder, rec);
    let b = decode_with(&sh.encoder, &pr);
    if a.0 != b.0 || a.1.iter().map(|x| x.to_bits()).collect::<Vec<_>>() != b.1.iter().map(|x| x.to_bits()).collect::<Vec<_>>() {
        return err("padded record does not decode identically (E7 Fix #5 padding assumption broken)");
    }
    Ok(pr)
}

fn decile(len: usize, cap: usize) -> usize {
    if cap == 0 { 0 } else { ((len * 10) / (cap + 1)).min(9) }
}

/// One list's plan.
#[derive(Default)]
struct ListPlan {
    t: usize,
    free1: Vec<usize>,
    free2: Vec<usize>,
    evict: Vec<usize>,
    /// (slot or position hint, doc index, weight); A2 slot = target slot.
    ins: Vec<(usize, usize, f32)>,
    /// Forward STARTs of the freed/evicted postings (A2b resolves by START).
    free1_s: Vec<usize>,
    free2_s: Vec<usize>,
    evict_s: Vec<usize>,
}

/// Run one batch end to end. `table` = readers.bin of the shard.
pub fn run_batch(sh: &mut Shard, recs: &[Rec], opts: &Opts, table: Arc<Table>) -> Result<Report> {
    let t_start = Instant::now();
    let arm = opts.arm;
    let mut rep = Report {
        arm: if opts.tail { format!("{}+tail", arm.name()) } else { arm.name().into() },
        tail: opts.tail,
        tail_reserve_words: sh.tail.reserve_words,
        tail_reserve_rows: sh.tail.reserve_rows,
        heap_reuse: opts.heap_reuse,
        safety: "dead-at-epoch only, no undo record".into(),
        writer_io: "MAP_SHARED atomic 8-byte stores (words, dir, override, header), 1-byte stores (inflation), plain copies into mapped unreachable bytes (holes, heap past bump); msync(MS_SYNC)+fdatasync; write()+rename only for forward_free.bin".into(),
        reuse_gate: "readers.bin, reuse iff freed epoch <= oldest live reader epoch; lease + same-namespace pid liveness".into(),
        infl_code_hist: vec![0; 256],
        inserted_by_len_decile: vec![0; 10],
        dropped_by_len_decile: vec![0; 10],
        heap_reserve: sh.heap_reserve,
        ..Default::default()
    };
    let (recovery, rs0) = recover_scan(sh, Some(&table))?;
    rep.recovery = recovery;
    let pubs = sh.published().unwrap();
    let e = pubs.epoch;
    let bank = (e & 1) as usize;
    rep.start_epoch = e;
    rep.heap_bytes_before = pubs.bump;
    rep.tail_words_before = pubs.tail_words;
    rep.tail_rows_before = pubs.tail_rows;
    {
        let pf0 = sh.read_posting_free()?;
        rep.heap_free_entries_before = pf0.entries.len() as u64;
        rep.heap_free_bytes_before = pf0.free_bytes();
    }
    if e + if arm.two_phase() { 2 } else { 1 } > TAG_MAX {
        return err("epoch would exceed 32767 (R4); a rebuild must reset tags");
    }
    let t_plan = Instant::now();
    let free0 = sh.read_free()?;
    rep.holes_before = free0.holes.len() as u64;
    let hole_starts: HashSet<u32> = free0.holes.iter().map(|h| h.start).collect();
    let map = id_map(sh, &rs0, &hole_starts)?;
    drop(rs0);

    // ---- resolve (last record per id wins)
    rep.records_in_batch = recs.len() as u64;
    let mut last: HashMap<u64, usize> = HashMap::new();
    for (i, r) in recs.iter().enumerate() {
        last.insert(r.id, i);
    }
    rep.superseded_in_batch = (recs.len() - last.len()) as u64;
    let mut del: HashMap<u32, (usize, FreePhase)> = HashMap::new();
    let mut docs: Vec<NewDoc> = Vec::new();
    let old_phase = if arm.old_at_fill() { FreePhase::P2 } else { FreePhase::P1 };
    for (i, r) in recs.iter().enumerate() {
        if last[&r.id] != i {
            continue;
        }
        let live = lookup(&map, r.id);
        match r.op {
            OP_DELETE => {
                rep.deletes_offered += 1;
                match live {
                    Some(row) => {
                        rep.deletes_applied += 1;
                        del.insert(sh.offs()[row] as u32, (row, FreePhase::P1));
                    }
                    None => rep.deletes_noop += 1,
                }
            }
            OP_UPSERT => {
                rep.docs_offered += 1;
                if let Some(row) = live {
                    rep.docs_updates += 1;
                    del.insert(sh.offs()[row] as u32, (row, old_phase));
                } else {
                    rep.docs_inserts += 1;
                }
                let mut comps = Vec::new();
                let mut vals = Vec::new();
                for (&c, &v) in r.comps.iter().zip(&r.vals) {
                    if (c as usize) < sh.dim && v > 0.0 {
                        comps.push(c);
                        vals.push(v);
                    } else {
                        rep.oov_components += 1;
                    }
                }
                let rec = encode_with(&sh.encoder, &comps, &vals);
                let (dc, dv) = decode_with(&sh.encoder, &rec);
                let (mut cc, mut vv) = (Vec::new(), Vec::new());
                for (c, v) in dc.into_iter().zip(dv) {
                    if v > 0.0 {
                        cc.push(c);
                        vv.push(v);
                    }
                }
                docs.push(NewDoc { id: r.id, comps: cc, vals: vv, rec, old_row: live, place: None, tail_candidate: false, n_inserted: 0 });
            }
            _ => unreachable!(),
        }
    }

    // ---- place records (Mechanism A): holes dead at the fill epoch's start
    let mut supply: BTreeMap<(u16, u32), Hole> = BTreeMap::new();
    for h in &free0.holes {
        supply.insert((h.len, h.start), *h);
    }
    if arm.two_phase() {
        for (&s, &(row, ph)) in &del {
            if ph == FreePhase::P1 {
                let h = Hole { start: s, len: row_len(sh, row) as u16, epoch: (e + 1) as u16 };
                supply.insert((h.len, h.start), h);
            }
        }
    }
    for d in docs.iter_mut() {
        let n = d.rec.len() as u16;
        let key = supply.range((n, 0)..).next().map(|(k, _)| *k);
        if let Some(k) = key {
            let h = supply.remove(&k).unwrap();
            let row = sh.row_of_start(h.start as usize).ok_or_else(|| Error::Msg(format!("hole at {} is not a row start", h.start)))?;
            d.place = Some(Place { start: h.start as usize, len: h.len as usize, row, hole: Some(h) });
        } else if opts.tail {
            d.tail_candidate = true;
        }
    }

    // ---- demand per list
    let cap_all = sh.lists.iter().map(|l| l.packed_postings_words).max().unwrap_or(0);
    let mut demand: Vec<Vec<(usize, f32)>> = vec![Vec::new(); sh.n_lists];
    for (di, d) in docs.iter().enumerate() {
        rep.postings_offered += d.comps.len() as u64;
        if !d.placed() {
            rep.postings_dropped_unplaced += d.comps.len() as u64;
            continue;
        }
        for (&c, &v) in d.comps.iter().zip(&d.vals) {
            let t = c as usize;
            if sh.list_len(t) < opts.hybrid_min_slots {
                rep.postings_spilled_hybrid += 1;
                continue;
            }
            demand[t].push((di, v));
        }
    }

    // ---- per-list plan, ascending term id (term-sorted apply)
    let mut plans: Vec<ListPlan> = Vec::new();
    let mut evicted_per_row: HashMap<usize, u32> = HashMap::new();
    let mut decodes = 0u64;
    let mut views: HashMap<usize, ListView> = HashMap::new();
    for t in 0..sh.n_lists {
        let need_view = !demand[t].is_empty();
        let view = sh.view(t, bank, false)?;
        let mut lp = ListPlan { t, ..Default::default() };
        let mut s_slots: Vec<usize> = Vec::new();
        let mut d0: Vec<usize> = Vec::new();
        for (i, &w) in view.words.iter().enumerate() {
            if visible(w, e) {
                match del.get(&(w_start(w) as u32)) {
                    Some((_, FreePhase::P1)) => lp.free1.push(i),
                    Some((_, FreePhase::P2)) => lp.free2.push(i),
                    None => s_slots.push(i),
                }
            } else if !arm.is_a2b() {
                d0.push(i);
            }
        }
        if lp.free1.is_empty() && lp.free2.is_empty() && !need_view {
            continue;
        }
        let cap = sh.list_len(t);
        let mut avail: Vec<usize> = match arm {
            Arm::A2 => d0.clone(),
            Arm::A2TwoPhase { .. } => {
                let mut a = d0.clone();
                a.extend(&lp.free1);
                a.sort_unstable();
                a
            }
            _ => Vec::new(),
        };
        let n_avail = if arm.is_a2b() { cap.saturating_sub(s_slots.len()) } else { avail.len() };
        let mut nd: Vec<(usize, f32)> = demand[t].clone();
        nd.sort_by(|a, b| b.1.total_cmp(&a.1).then(docs[a.0].id.cmp(&docs[b.0].id)));
        let take = nd.len().min(n_avail);
        let dec = decile(cap, cap_all);
        for k in 0..take {
            let slot = if arm.is_a2b() { usize::MAX } else { avail[k] };
            lp.ins.push((slot, nd[k].0, nd[k].1));
        }
        if !arm.is_a2b() {
            avail.drain(0..take);
        }
        let rest = &nd[take..];
        if !rest.is_empty() && arm.evicts() {
            let lm = sh.list_min(t);
            let min_ok = lm >> 63 == 0 && !arm.is_a2b() && {
                let ms = ((lm >> 32) & 0xFFFF) as usize;
                s_slots.binary_search(&ms).is_ok()
            };
            let min_w = f32::from_bits((lm & 0xFFFF_FFFF) as u32);
            if !(min_ok && rest[0].1 <= min_w) {
                rep.lists_decoded_for_eviction += 1;
                let mut sw: Vec<(f32, usize)> = s_slots
                    .iter()
                    .map(|&i| {
                        decodes += 1;
                        let w = view.words[i];
                        (sh.weight_in(w_start(w), w_len(w), t as u16).unwrap_or(0.0), i)
                    })
                    .collect();
                sw.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)));
                let mut acc = 0;
                while acc < rest.len() && acc < sw.len() && rest[acc].1 > sw[acc].0 {
                    acc += 1;
                }
                for k in 0..acc {
                    let slot = sw[k].1;
                    lp.evict.push(slot);
                    let row = sh.row_of_start(w_start(view.words[slot])).unwrap();
                    *evicted_per_row.entry(row).or_default() += 1;
                    let ts = if arm.is_a2b() { usize::MAX } else { slot };
                    lp.ins.push((ts, rest[k].0, rest[k].1));
                }
                rep.postings_evicted += acc as u64;
                rep.postings_dropped_capacity += (rest.len() - acc) as u64;
                rep.dropped_by_len_decile[dec] += (rest.len() - acc) as u64;
            } else {
                rep.postings_dropped_capacity += rest.len() as u64;
                rep.dropped_by_len_decile[dec] += rest.len() as u64;
            }
        } else {
            rep.postings_dropped_capacity += rest.len() as u64;
            rep.dropped_by_len_decile[dec] += rest.len() as u64;
        }
        rep.inserted_by_len_decile[dec] += lp.ins.len() as u64;
        for &(_, di, _) in &lp.ins {
            docs[di].n_inserted += 1;
        }
        rep.postings_freed += (lp.free1.len() + lp.free2.len()) as u64;
        lp.free1_s = lp.free1.iter().map(|&i| w_start(view.words[i])).collect();
        lp.free2_s = lp.free2.iter().map(|&i| w_start(view.words[i])).collect();
        lp.evict_s = lp.evict.iter().map(|&i| w_start(view.words[i])).collect();
        views.insert(t, view);
        plans.push(lp);
    }
    rep.lists_touched = plans.len() as u64;
    rep.postings_inserted = plans.iter().map(|p| p.ins.len() as u64).sum();

    // ---- docs with zero inserted postings are unplaced (hole unused, no tail space)
    for d in docs.iter_mut() {
        if d.placed() && d.n_inserted == 0 {
            d.place = None;
            d.tail_candidate = false;
            rep.docs_unplaced_no_posting += 1;
        }
    }
    // ---- tail append (+tail): remaining candidates in batch order, at the
    // published bump (header field 64), rows n_docs + published tail rows + j
    // (field 72). Refused before any write when the reserve is exhausted.
    let mut tail_w_new = pubs.tail_words;
    let mut tail_r_new = pubs.tail_rows;
    for d in docs.iter_mut() {
        if !d.tail_candidate {
            continue;
        }
        let start = sh.fdw as u64 + tail_w_new;
        let row = sh.n_docs as u64 + tail_r_new;
        d.place = Some(Place { start: start as usize, len: d.rec.len(), row: row as usize, hole: None });
        d.tail_candidate = false;
        tail_w_new += d.rec.len() as u64;
        tail_r_new += 1;
    }
    if tail_w_new > sh.tail.reserve_words || tail_r_new > sh.tail.reserve_rows {
        return err(format!(
            "forward tail exhausted: batch needs {} tail words / {} tail rows at ({}, {}) > reserve ({}, {}); nothing of this batch was written",
            tail_w_new - pubs.tail_words, tail_r_new - pubs.tail_rows, pubs.tail_words, pubs.tail_rows, sh.tail.reserve_words, sh.tail.reserve_rows
        ));
    }
    rep.docs_placed_hole = docs.iter().filter(|d| d.place.is_some_and(|p| p.hole.is_some())).count() as u64;
    rep.docs_placed_tail = docs.iter().filter(|d| d.place.is_some_and(|p| p.hole.is_none())).count() as u64;
    rep.docs_placed = rep.docs_placed_hole + rep.docs_placed_tail;
    rep.docs_unplaced_no_hole = rep.docs_offered - rep.docs_placed - rep.docs_unplaced_no_posting;

    // ---- rows fully evicted (visible count drops to 0) become holes (P1)
    let mut fully_evicted: Vec<usize> = Vec::new();
    if !evicted_per_row.is_empty() {
        let rs = scan_rows(sh, bank, e)?;
        for (&row, &n) in &evicted_per_row {
            if rs.visible[row] == n && !del.contains_key(&(sh.offs()[row] as u32)) {
                fully_evicted.push(row);
            }
        }
    }
    rep.rows_fully_evicted = fully_evicted.len() as u64;
    rep.record_decodes = decodes;
    rep.plan_s = t_plan.elapsed().as_secs_f64();

    // ---- free list after each phase
    let used: HashSet<u32> = docs.iter().filter_map(|d| d.place.and_then(|p| p.hole).map(|h| h.start)).collect();
    let tag1 = e + 1;
    let tag2 = e + 2;
    let final_tag = if arm.two_phase() { tag2 } else { tag1 };
    let hole_of = |row: usize, ep: u64| Hole { start: sh.offs()[row] as u32, len: row_len(sh, row) as u16, epoch: ep as u16 };
    let mut fl1 = FreeList { epoch: tag1, holes: free0.holes.clone() };
    for (_, &(row, ph)) in &del {
        if ph == FreePhase::P1 || !arm.two_phase() {
            fl1.holes.push(hole_of(row, tag1));
        }
    }
    for &row in &fully_evicted {
        fl1.holes.push(hole_of(row, tag1));
    }
    rep.rows_freed = (del.len() + fully_evicted.len()) as u64;
    let mut fl_final = FreeList { epoch: final_tag, holes: fl1.holes.iter().copied().filter(|h| !used.contains(&h.start)).collect() };
    if arm.two_phase() {
        for (_, &(row, ph)) in &del {
            if ph == FreePhase::P2 {
                fl_final.holes.push(hole_of(row, tag2));
            }
        }
    }
    rep.holes_after = fl_final.holes.len() as u64;

    // ---- execute
    let mut cur_bump = pubs.bump;
    let mut tail_state = TailState { words: pubs.tail_words, rows: pubs.tail_rows, words_new: tail_w_new, rows_new: tail_r_new };
    let apply_t0 = Instant::now();
    if arm.two_phase() {
        let p1 = exec_phase(sh, &table, opts, arm, &plans, &views, &docs, e, tag1, Phase::Free, &fl1, &mut cur_bump, &mut tail_state, &mut rep, apply_t0)?;
        rep.phases.push(p1);
        if opts.stop_after_first_flip {
            return Err(Error::Injected(sh.wlog.n_ops));
        }
        if !opts.hold_between_flips.is_zero() {
            std::thread::sleep(opts.hold_between_flips);
        }
        let views2: HashMap<usize, ListView> = if arm.is_a2b() {
            let mut v = HashMap::new();
            for p in &plans {
                v.insert(p.t, sh.view(p.t, (tag1 & 1) as usize, false)?);
            }
            v
        } else {
            views.clone()
        };
        let p2 = exec_phase(sh, &table, opts, arm, &plans, &views2, &docs, tag1, tag2, Phase::Fill, &fl_final, &mut cur_bump, &mut tail_state, &mut rep, apply_t0)?;
        rep.gap_s = p2.flip_done_at_s - rep.phases[0].flip_done_at_s;
        rep.phases.push(p2);
    } else {
        let p = exec_phase(sh, &table, opts, arm, &plans, &views, &docs, e, tag1, Phase::Both, &fl_final, &mut cur_bump, &mut tail_state, &mut rep, apply_t0)?;
        rep.phases.push(p);
    }
    rep.end_epoch = sh.epoch();
    rep.heap_bytes_after = cur_bump;
    rep.tail_words_after = tail_state.words;
    rep.tail_rows_after = tail_state.rows;
    {
        let pf1 = sh.read_posting_free()?;
        rep.heap_free_entries_after = pf1.entries.len() as u64;
        rep.heap_free_bytes_after = pf1.free_bytes();
    }
    rep.logical_bytes = sh.wlog.logical_bytes;
    rep.write_ops = sh.wlog.n_ops;
    rep.total_s = t_start.elapsed().as_secs_f64();
    sh.flush_log()?;
    Ok(rep)
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Free,
    Fill,
    Both,
}

/// Published tail counters (words, rows) and the values the FILL flip publishes.
struct TailState {
    words: u64,
    rows: u64,
    words_new: u64,
    rows_new: u64,
}

#[allow(clippy::too_many_arguments)]
fn exec_phase(
    sh: &mut Shard,
    table: &Table,
    opts: &Opts,
    arm: Arm,
    plans: &[ListPlan],
    views: &HashMap<usize, ListView>,
    docs: &[NewDoc],
    e_pub: u64,
    tag: u64,
    phase: Phase,
    fl: &FreeList,
    bump: &mut u64,
    tail: &mut TailState,
    rep: &mut Report,
    t0: Instant,
) -> Result<PhaseReport> {
    let mut pr = PhaseReport { epoch: tag, ..Default::default() };
    let mut cleared = 0u64;
    pr.wait_readers_s = gate(table, e_pub, opts.reader_timeout, &mut cleared)?;
    let tw = Instant::now();
    // The posting free list at e_pub (recovery made it trusted at the batch
    // start; a FREE phase rewrote it for e_pub = e+1). Entries stamped
    // <= e_pub are reusable: the gate above established oldest >= e_pub.
    let pf_in = sh.read_posting_free()?;
    if pf_in.epoch != e_pub {
        return err(format!("posting_free.bin epoch {} != published {e_pub} at phase start", pf_in.epoch));
    }
    let mut halloc = HeapAlloc::new(&pf_in, e_pub, opts.heap_reuse, *bump, sh.heap_reserve, sh.heap_base);
    let mut superseded: Vec<HeapEntry> = Vec::new();
    let fill_pre = phase != Phase::Free;
    let free_now_pre = |ph_is_p2: bool| -> bool {
        match phase {
            Phase::Both => true,
            Phase::Free => !ph_is_p2,
            Phase::Fill => ph_is_p2,
        }
    };
    let mut a2b_units: Vec<(usize, Vec<u8>, u64, u64, u64, u64)> = Vec::new();
    if arm.is_a2b() {
        let mut total = 0usize;
        let mut dec_pre = 0u64;
        let from_bank = (e_pub & 1) as usize;
        for lp in plans {
            let t = lp.t;
            let mut remove: HashSet<usize> = HashSet::new();
            if free_now_pre(false) {
                remove.extend(&lp.free1_s);
                remove.extend(&lp.evict_s);
            }
            if free_now_pre(true) {
                remove.extend(&lp.free2_s);
            }
            let ins: Vec<usize> = if fill_pre { lp.ins.iter().map(|&(_, di, _)| di).collect() } else { Vec::new() };
            if remove.is_empty() && ins.is_empty() {
                continue;
            }
            let (body, man, weights) = a2b_rewrite(sh, &views[&t], &remove, &ins, docs, rep, &mut dec_pre)?;
            let unit = build_unit(t as u32, tag as u32, &man, &body);
            total += unit.len();
            let best = weights.iter().enumerate().fold(None, |b: Option<(f32, usize)>, (i, &w)| match b {
                Some((bw, bs)) if bw <= w => Some((bw, bs)),
                _ => Some((w, i)),
            });
            let Some(off) = halloc.alloc(unit.len() as u64) else {
                return err(format!(
                    "posting heap exhausted: epoch {tag} needs {total} B (unit of list {t}: {} B) with {} B reusable and bump {} of reserve {} (R7); nothing of this epoch was written",
                    unit.len(), pf_in.entries.iter().filter(|x| opts.heap_reuse && x.epoch <= e_pub).map(|x| x.len).sum::<u64>(), *bump, sh.heap_reserve
                ));
            };
            let prev = sh.dir_entry(from_bank, t);
            if prev != sh.native_off(t) && prev >= sh.heap_base {
                let (uh, _) = parse_unit(sh.bytes(F::Heap), (prev - sh.heap_base) as usize)?;
                superseded.push(HeapEntry { off: prev, len: unit_len(uh.body_bytes), epoch: tag });
            }
            a2b_units.push((t, unit, min_word(best, tag), remove.len() as u64, ins.len() as u64, off));
        }
        rep.record_decodes += dec_pre;
    }
    let from = (e_pub & 1) as usize;
    let to = (tag & 1) as usize;
    let nbt = sh.n_blocks_total;
    let nl = sh.n_lists;
    copy_bank(sh, F::Infl, nbt, from, to)?;
    copy_bank(sh, F::Dir, 8 * nl, from, to)?;
    let fill = phase != Phase::Free;
    let free_now = |ph_is_p2: bool| -> bool {
        match phase {
            Phase::Both => true,
            Phase::Free => !ph_is_p2,
            Phase::Fill => ph_is_p2,
        }
    };

    // forward records + overrides (fill); tail records also extend the CSR
    // (offsets[row + 1]); every byte is unreachable until the flip.
    if fill {
        for d in docs {
            if let Some(p) = d.place {
                if p.hole.is_some() {
                    let pr_rec = padded_record(sh, &d.rec, p.len)?;
                    sh.w_bytes(F::Fwd, 8 * p.start, bytemuck::cast_slice(&pr_rec))?;
                } else {
                    debug_assert_eq!(p.len, d.rec.len());
                    sh.w_bytes(F::Fwd, 8 * p.start, bytemuck::cast_slice(&d.rec))?;
                    sh.w_u64(F::Offs, 8 * (p.row + 1), (p.start + p.len) as u64)?;
                    pr.tail_records_written += 1;
                }
                sh.w_u64(F::Ovr, 8 * p.row, FREE_BIT | d.id)?;
                pr.records_written += 1;
            }
        }
    }

    let mut lmin_writes: Vec<(usize, u64)> = Vec::new();
    let mut decodes = 0u64;
    if !arm.is_a2b() {
        let infl_bank_base = to * nbt;
        for lp in plans {
            let t = lp.t;
            let view = &views[&t];
            let cur: Vec<u64> = (0..sh.list_len(t)).map(|i| sh.word(t, i)).collect();
            let mut marks: Vec<usize> = Vec::new();
            if free_now(false) {
                marks.extend(&lp.free1);
                if arm.evicts() {
                    marks.extend(&lp.evict);
                }
            }
            if free_now(true) {
                marks.extend(&lp.free2);
            }
            for &i in &marks {
                let w = cur[i];
                if !visible(w, e_pub) {
                    return err(format!("list {t} slot {i}: delete mark on a slot not visible at {e_pub}"));
                }
                sh.w_u64(F::Pl, sh.locs[t].pp + 8 * i, FREE_BIT | (tag << 48) | (w & 0xFFFF_FFFF_FFFF))?;
                pr.marks += 1;
            }
            let mut ins_w: Vec<(usize, f32)> = Vec::new();
            if fill && !lp.ins.is_empty() {
                let blocks = crate::summary::decode_summary(sh.pl(), &sh.locs[t], &sh.lists[t]);
                let base = sh.block_base[t];
                let mut codes: HashMap<usize, u8> = HashMap::new();
                for &(slot, di, wt) in &lp.ins {
                    let d = &docs[di];
                    let h = d.place.unwrap();
                    let old = sh.word(t, slot);
                    if visible(old, e_pub) || w_tag(old) > e_pub {
                        return err(format!("list {t} slot {slot}: insert target is not dead at {e_pub}"));
                    }
                    sh.w_u64(F::Pl, sh.locs[t].pp + 8 * slot, make_word(h.start, h.len, tag, false))?;
                    pr.fills += 1;
                    ins_w.push((slot, wt));
                    let j = view.block_of(slot);
                    let blk: &RawBlock = &blocks[j];
                    let mut ratio = 1.0f64;
                    for (&c, &w) in d.comps.iter().zip(&d.vals) {
                        match blk.get(c) {
                            Some(old) if old > 0.0 => ratio = ratio.max((w as f64 / old as f64).max(1.0)),
                            _ => {
                                rep.blind_components += 1;
                                rep.blind_mass += w as f64;
                            }
                        }
                    }
                    let need = ((ratio - 1.0) * 32.0 * 1e9).round() / 1e9;
                    let need = need.ceil();
                    let need = if need > 254.0 { 255u8 } else { need as u8 };
                    let cur = *codes.entry(j).or_insert_with(|| sh.infl(to, base + j));
                    if need > cur {
                        codes.insert(j, need);
                    }
                }
                for (j, c) in codes {
                    if c != sh.infl(to, base + j) {
                        sh.w_u8(F::Infl, infl_bank_base + base + j, c)?;
                        rep.infl_blocks_raised += 1;
                        rep.infl_code_hist[c as usize] += 1;
                        if c == 255 {
                            rep.infl_saturated += 1;
                        }
                    }
                }
            }
            // list_min for the state published by this flip
            let _ = view;
            let mut new_words = cur.clone();
            for &i in &marks {
                new_words[i] = FREE_BIT | (tag << 48) | (cur[i] & 0xFFFF_FFFF_FFFF);
            }
            if fill {
                for &(slot, di, _) in &lp.ins {
                    let h = docs[di].place.unwrap();
                    new_words[slot] = make_word(h.start, h.len, tag, false);
                }
            }
            let lm = sh.list_min(t);
            let old_slot = ((lm >> 32) & 0xFFFF) as usize;
            let old_alive = lm >> 63 == 0 && old_slot < cur.len() && visible(cur[old_slot], e_pub) && visible(new_words[old_slot], tag);
            let nm = if old_alive {
                let mut best = (f32::from_bits((lm & 0xFFFF_FFFF) as u32), old_slot);
                for &(s, w) in &ins_w {
                    if w < best.0 || (w == best.0 && s < best.1) {
                        best = (w, s);
                    }
                }
                min_word(Some(best), tag)
            } else if lm >> 63 == 1 && marks.is_empty() {
                let best = ins_w.iter().fold(None, |b: Option<(f32, usize)>, &(s, w)| match b {
                    Some((bw, bs)) if bw < w || (bw == w && bs < s) => Some((bw, bs)),
                    _ => Some((w, s)),
                });
                min_word(best, tag)
            } else {
                rep.lists_min_recomputed += 1;
                full_min(sh, &new_words, t, tag, tag, &mut decodes)
            };
            if nm != lm {
                lmin_writes.push((t, nm));
            }
        }
    } else {
        // A2b: units were built and allocated (reuse or bump) before any write
        for (t, unit, nm, n_rm, n_ins, uoff) in a2b_units.drain(..) {
            let off = (uoff - sh.heap_base) as usize;
            sh.w_bytes(F::Heap, off, &unit)?;
            sh.w_u64(F::Dir, 8 * (to * nl + t), uoff)?;
            pr.units_written += 1;
            pr.unit_bytes += unit.len() as u64;
            rep.a2b_lists_rewritten += 1;
            pr.marks += n_rm;
            pr.fills += n_ins;
            if nm != sh.list_min(t) {
                lmin_writes.push((t, nm));
            }
        }
    }
    rep.record_decodes += decodes;
    for (t, m) in &lmin_writes {
        sh.w_u64(F::Lmin, 8 * t, *m)?;
    }
    for f in [F::Fwd, F::Offs, F::Ovr, F::Pl, F::Infl, F::Heap, F::Dir, F::Lmin] {
        sh.sync(f)?;
    }
    *bump = halloc.bump;
    pr.heap_reused_units = halloc.reused_units;
    pr.heap_reused_bytes = halloc.reused_bytes;
    pr.heap_bumped_bytes = halloc.bumped_bytes;
    pr.heap_superseded_bytes = superseded.iter().map(|x| x.len).sum();
    rep.heap_reused_units += pr.heap_reused_units;
    rep.heap_reused_bytes += pr.heap_reused_bytes;
    rep.heap_bumped_bytes += pr.heap_bumped_bytes;
    rep.heap_superseded_bytes += pr.heap_superseded_bytes;
    let pf_out = halloc.finish(superseded, tag);
    sh.replace_file("posting_free.bin", &pf_out.serialize())?;
    let fl_bytes = fl.serialize();
    if !opts.replace_after_flip {
        sh.replace_file("forward_free.bin", &fl_bytes)?;
    }
    if fill {
        tail.words = tail.words_new;
        tail.rows = tail.rows_new;
    }
    let flip_start_ns = crate::readers::now_ns();
    sh.write_header(tag, *bump, tail.words, tail.rows)?;
    if opts.replace_after_flip {
        sh.replace_file("forward_free.bin", &fl_bytes)?;
    }
    pr.write_s = tw.elapsed().as_secs_f64();
    pr.flip_done_at_s = t0.elapsed().as_secs_f64();
    if let Ok(pth) = std::env::var("INPLACE_PROGRESS") {
        use std::io::Write as _;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(pth) {
            let _ = writeln!(f, "flip {tag} {:.6} start_ns {flip_start_ns} end_ns {}", pr.flip_done_at_s, crate::readers::now_ns());
        }
    }
    pr.stale_reader_slots_cleared = cleared;
    Ok(pr)
}

/// Rewrite one list for A2b: drop the postings whose forward START is in
/// `remove`, add the docs `ins` (each to the block with the largest summary
/// dot), recompute the summary of every changed block exactly as the build
/// does (energy-preserving over the members' served values, then the build's
/// quantisation), drop emptied blocks. Returns (body, manifest, per-posting
/// weight of term t).
fn a2b_rewrite(
    sh: &Shard,
    view: &ListView,
    remove: &HashSet<usize>,
    ins: &[usize],
    docs: &[NewDoc],
    rep: &mut Report,
    decodes: &mut u64,
) -> Result<(Vec<u8>, crate::layout::ListManifest, Vec<f32>)> {
    let t = view.t;
    let mut v = view.clone();
    if v.blocks.is_empty() && v.man.n_summaries > 0 {
        let (bytes, loc) = match v.unit {
            None => (sh.pl(), sh.locs[t].clone()),
            Some(off) => (sh.bytes(F::Heap), crate::layout::walk_one(&v.man, off as usize + crate::lists::UNIT_HEADER)),
        };
        v.blocks = crate::summary::decode_summary(bytes, &loc, &v.man);
    }
    let mut nb = v.blocks.len();
    let mut members: Vec<Vec<u64>> = vec![Vec::new(); nb];
    let mut changed = vec![false; nb];
    let mut removed = 0usize;
    for j in 0..nb {
        for i in v.bo[j]..v.bo[j + 1] {
            let w = v.words[i];
            if remove.contains(&w_start(w)) {
                changed[j] = true;
                removed += 1;
            } else {
                members[j].push(w);
            }
        }
    }
    if removed != remove.len() {
        return err(format!("list {t}: {} postings to remove, {removed} found", remove.len()));
    }
    if nb == 0 && !ins.is_empty() {
        v.blocks.push(RawBlock { comps: Vec::new(), codes: Vec::new(), min: 0.0, quant: 0.0 });
        members.push(Vec::new());
        changed.push(true);
        nb = 1;
    }
    for &di in ins {
        let d = &docs[di];
        let mut best = (f32::NEG_INFINITY, 0usize);
        for (j, b) in v.blocks.iter().enumerate() {
            let s = b.dot(&d.comps, &d.vals);
            if s > best.0 {
                best = (s, j);
            }
        }
        let h = d.place.unwrap();
        members[best.1].push(make_word(h.start, h.len, 0, false));
        changed[best.1] = true;
    }
    // New members' vectors come from the plan (their records may not be
    // written yet when the units are pre-built).
    let new_start: HashMap<usize, usize> = ins.iter().map(|&di| (docs[di].place.unwrap().start, di)).collect();
    let mut words = Vec::new();
    let mut bo = vec![0usize];
    let mut blocks = Vec::new();
    let mut weights = Vec::new();
    for j in 0..nb {
        if members[j].is_empty() {
            rep.a2b_blocks_removed += 1;
            continue;
        }
        let decs: Vec<(Vec<u16>, Vec<f32>)> = members[j]
            .iter()
            .map(|&w| match new_start.get(&w_start(w)) {
                Some(&di) => (docs[di].comps.clone(), docs[di].vals.clone()),
                None => {
                    *decodes += 1;
                    sh.decode(w_start(w), w_len(w))
                }
            })
            .collect();
        for (c, vv) in &decs {
            weights.push(c.binary_search(&(t as u16)).ok().map(|i| vv[i]).unwrap_or(0.0));
        }
        if changed[j] {
            let refs: Vec<(&[u16], &[f32])> = decs.iter().map(|(c, v)| (c.as_slice(), v.as_slice())).collect();
            let (sc, sv) = energy_summary(&refs, sh.alpha);
            blocks.push(raw_from_values(sc, &sv));
            rep.a2b_blocks_recomputed += 1;
        } else {
            blocks.push(v.blocks[j].clone());
        }
        words.extend_from_slice(&members[j]);
        bo.push(words.len());
    }
    if words.is_empty() {
        bo.clear();
    }
    let (body, man) = encode_list(&words, &bo, &blocks, v.man.dim);
    Ok((body, man, weights))
}

/// Convenience: open, run, and return the report.
pub fn run_path(dir: &Path, recs: &[Rec], opts: &Opts) -> Result<Report> {
    let mut sh = Shard::open(dir)?;
    let table = Arc::new(Table::open(&dir.join("readers.bin"))?);
    run_batch(&mut sh, recs, opts, table)
}
