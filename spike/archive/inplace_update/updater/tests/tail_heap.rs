//! Tests for the 2026-09-30 additions on SYNTHETIC v3.1 shards the crate
//! builds itself: the `+tail` forward append (FORMAT_V3 §3.R4 / rev. 6) and
//! A2b heap reuse (R7, `posting_free.bin`). Work dirs under $INPLACE_TEST_DIR
//! (default /home/vscode/work/inplace_update/stage3/updater/tests).

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;

use inplace_updater::apply::{recover, run_batch, Arm, Opts, Report};
use inplace_updater::batch::{Rec, OP_DELETE, OP_UPSERT};
use inplace_updater::plsim::{load_ops, materialize, restore};
use inplace_updater::readers::{ReaderGuard, Table};
use inplace_updater::search::{search_at, Hit, Query};
use inplace_updater::store::{decode_with, encode_with, visible, w_len, w_start, Shard, F, OP_NEWFILE, OP_SYNC, OP_WRITE};
use inplace_updater::synth::{build, random_vec, SynthParams};
use inplace_updater::util::{fnv1a64, Error};
use inplace_updater::verify::verify;

fn root() -> PathBuf {
    PathBuf::from(std::env::var("INPLACE_TEST_DIR").unwrap_or("/home/vscode/work/inplace_update/stage3/updater/tests".into()))
}

fn params() -> SynthParams {
    SynthParams { n_docs: 1500, dim: 160, cap: 40, block: 6, nnz_min: 4, nnz_max: 16, seed: 11, heap_factor: 8, id_base: 1_000_000, tail_words: 4096, tail_rows: 400 }
}

type Base = Vec<(u64, Vec<u16>, Vec<f32>)>;

fn fresh(name: &str, p: &SynthParams) -> (PathBuf, Base) {
    let d = root().join(name);
    let _ = std::fs::remove_dir_all(&d);
    let base = build(&d, p).unwrap();
    (d, base)
}

fn copy_dir(a: &Path, b: &Path) {
    let _ = std::fs::remove_dir_all(b);
    std::fs::create_dir_all(b).unwrap();
    for e in std::fs::read_dir(a).unwrap() {
        let e = e.unwrap();
        if e.file_type().unwrap().is_file() {
            std::fs::copy(e.path(), b.join(e.file_name())).unwrap();
        }
    }
    inplace_updater::guard::write_sentinel(b, "test-copy").unwrap();
}

fn file_hashes(d: &Path) -> HashMap<String, u64> {
    let mut out = HashMap::new();
    for e in std::fs::read_dir(d).unwrap() {
        let e = e.unwrap();
        let n = e.file_name().to_string_lossy().to_string();
        if e.file_type().unwrap().is_file() && n != "readers.bin" && n != ".inplace_work_copy" {
            out.insert(n, fnv1a64(&std::fs::read(e.path()).unwrap()));
        }
    }
    out
}

/// Deletes, updates (new vectors), inserts (fresh ids) over `live` docs.
fn make_batch(live: &Base, dim: usize, seed: u64, n_del: usize, n_upd: usize, n_ins: usize, id_off: u64) -> Vec<Rec> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut idx: Vec<usize> = (0..live.len()).collect();
    for i in (1..idx.len()).rev() {
        let j = rng.random_range(0..=i);
        idx.swap(i, j);
    }
    let mut recs = Vec::new();
    for &i in &idx[..n_del] {
        recs.push(Rec { op: OP_DELETE, id: live[i].0, comps: vec![], vals: vec![] });
    }
    for &i in &idx[n_del..n_del + n_upd] {
        let (c, v) = random_vec(&mut rng, dim, 4, 14);
        recs.push(Rec { op: OP_UPSERT, id: live[i].0, comps: c, vals: v });
    }
    for k in 0..n_ins {
        let (c, v) = random_vec(&mut rng, dim, 4, 14);
        recs.push(Rec { op: OP_UPSERT, id: 900_000_000 + id_off + k as u64, comps: c, vals: v });
    }
    recs
}

/// The live doc set after `recs` (for the next batch and the reference scorer).
fn apply_model(live: &Base, recs: &[Rec]) -> Base {
    let mut m: HashMap<u64, (Vec<u16>, Vec<f32>)> = live.iter().map(|(id, c, v)| (*id, (c.clone(), v.clone()))).collect();
    for r in recs {
        if r.op == OP_DELETE {
            m.remove(&r.id);
        } else {
            m.insert(r.id, (r.comps.clone(), r.vals.clone()));
        }
    }
    let mut out: Base = m.into_iter().map(|(id, (c, v))| (id, c, v)).collect();
    out.sort_by_key(|x| x.0);
    out
}

fn queries(dim: usize, n: usize, seed: u64) -> Vec<Query> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    (0..n)
        .map(|_| {
            let (c, v) = random_vec(&mut rng, dim, 6, 10);
            Query { comps: c, vals: v }
        })
        .collect()
}

fn results(sh: &Shard, e: u64, qs: &[Query]) -> Vec<Vec<Hit>> {
    qs.iter().map(|q| search_at(sh, e, q, 20, Duration::ZERO, None).unwrap()).collect()
}

fn run(dir: &Path, recs: &[Rec], opts: &Opts) -> Result<Report, Error> {
    let mut sh = Shard::open(dir).unwrap();
    let table = Arc::new(Table::open(&dir.join("readers.bin")).unwrap());
    run_batch(&mut sh, recs, opts, table)
}

fn assert_verified(dir: &Path) -> inplace_updater::verify::VerifyReport {
    let sh = Shard::open(dir).unwrap();
    let v = verify(&sh, true).unwrap();
    assert!(v.ok(), "verify failed: {:?}", v.violations);
    v
}

/// Visible (list -> set of ext ids) at epoch e.
fn visible_ids(sh: &Shard, e: u64) -> Vec<HashSet<u64>> {
    let bank = (e & 1) as usize;
    (0..sh.n_lists)
        .map(|t| {
            let v = sh.view(t, bank, false).unwrap();
            v.words.iter().filter(|&&w| visible(w, e)).map(|&w| sh.ext_id(sh.row_of_start(w_start(w)).unwrap())).collect()
        })
        .collect()
}

/// I11-style model checks: no deleted id visible, new docs only in lists of
/// their components, records decode to the new vectors, no list grew.
fn model_checks(dir: &Path, recs: &[Rec], before: &[HashSet<u64>], cap: usize) {
    let sh = Shard::open(dir).unwrap();
    let e = sh.epoch();
    let after = visible_ids(&sh, e);
    let mut last: HashMap<u64, &Rec> = HashMap::new();
    for r in recs {
        last.insert(r.id, r);
    }
    for t in 0..sh.n_lists {
        assert!(after[t].len() <= cap.max(before[t].len()), "list {t} grew");
        for id in &after[t] {
            match last.get(id) {
                Some(r) if r.op == OP_DELETE => panic!("deleted id {id} visible in list {t}"),
                Some(r) => assert!(r.comps.contains(&(t as u16)), "new doc {id} in list {t} without that component"),
                None => assert!(before[t].contains(id), "list {t}: id {id} appeared from nowhere"),
            }
        }
    }
    let bank = (e & 1) as usize;
    for t in 0..sh.n_lists {
        let v = sh.view(t, bank, false).unwrap();
        for &w in &v.words {
            if !visible(w, e) {
                continue;
            }
            let row = sh.row_of_start(w_start(w)).unwrap();
            let id = sh.ext_id(row);
            if let Some(r) = last.get(&id) {
                let (c, _) = sh.decode(w_start(w), w_len(w));
                assert!(c.iter().all(|x| r.comps.contains(x)), "record of {id} (row {row}) does not decode to its new vector");
            }
        }
    }
}

/// Clean reference: the same exact scorer as `search_at`, but every candidate's
/// values come from the MODEL vectors (base or batch vector, encoded and
/// decoded with the shard's encoder), not from the shard's records; ids come
/// from the model, candidates from the visible (list, id) sets. Bit-identical
/// hits prove tail records and overrides resolve to the right doc.
fn reference_hits(sh: &Shard, e: u64, live: &Base, qs: &[Query]) -> Vec<Vec<Hit>> {
    let vis = visible_ids(sh, e);
    let vecs: HashMap<u64, (Vec<u16>, Vec<f32>)> = live
        .iter()
        .map(|(id, c, v)| {
            let rec = encode_with(&sh.encoder, c, v);
            (*id, decode_with(&sh.encoder, &rec))
        })
        .collect();
    qs.iter()
        .map(|q| {
            let mut cands: HashSet<u64> = HashSet::new();
            for &t in &q.comps {
                if (t as usize) < sh.n_lists {
                    cands.extend(vis[t as usize].iter().copied());
                }
            }
            let mut hits: Vec<(f32, u64)> = cands
                .into_iter()
                .map(|id| {
                    let (c, v) = &vecs[&id];
                    let mut acc = 0f32;
                    for (qc, qv) in q.comps.iter().zip(&q.vals) {
                        if let Ok(i) = c.binary_search(qc) {
                            acc += qv * v[i];
                        }
                    }
                    (acc, id)
                })
                .collect();
            hits.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
            hits.truncate(20);
            hits.into_iter().map(|(s, id)| Hit { id, score_bits: s.to_bits() }).collect()
        })
        .collect()
}

fn tail_opts(arm: Arm) -> Opts {
    Opts { arm, tail: true, ..Default::default() }
}

// ------------------------------------------------------------------ +tail

#[test]
fn t_tail_open_identity() {
    let p = params();
    let (d, _) = fresh("t_tail_open", &p);
    let v = assert_verified(&d);
    assert_eq!((v.tail_words, v.tail_rows), (0, 0));
    let sh = Shard::open(&d).unwrap();
    assert_eq!(sh.tail.reserve_words, p.tail_words);
    assert_eq!(sh.tail.reserve_rows, p.tail_rows);
    assert_eq!(sh.offs().len(), p.n_docs + 1 + p.tail_rows as usize);
    assert_eq!(sh.fwd().len(), sh.fdw + p.tail_words as usize);
    for t in 0..sh.n_lists {
        let v = sh.view(t, 0, true).unwrap();
        let (body, man) = inplace_updater::summary::encode_list(&v.words, &v.bo, &v.blocks, v.man.dim);
        assert_eq!(&body[..], &sh.pl()[sh.locs[t].pp..sh.locs[t].end], "list {t} re-encode differs");
        assert_eq!(man, sh.lists[t]);
    }
}

/// A2+tail / A2b+tail: batch 1 places every doc with a surviving posting
/// (all via the tail), batch 2 uses holes first, batch 3 reuses tail-row holes.
/// A2 one flip inserts only into slots dead at E, so a fresh copy takes no
/// posting and hence no record even with `+tail` (`pre` = a delete-only
/// batch first, which also leaves `n_pre` holes). A2b takes posting space
/// from the heap, so its first batch goes entirely to the tail.
fn tail_arm(name: &str, arm: Arm, pre: bool) {
    let p = params();
    let (d, base0) = fresh(name, &p);
    let qs = queries(p.dim, 25, 5);
    let n_pre = 30;
    let (base, e0) = if pre {
        let b0 = make_batch(&base0, p.dim, 0, n_pre, 0, 0, 0);
        let r0 = run(&d, &b0, &tail_opts(arm)).unwrap();
        assert_eq!((r0.docs_offered, r0.deletes_applied), (0, n_pre as u64));
        (apply_model(&base0, &b0), 1u64)
    } else {
        (base0.clone(), 0u64)
    };
    let before = visible_ids(&Shard::open(&d).unwrap(), e0);
    let b1 = make_batch(&base, p.dim, 1, 60, 120, 40, 0);
    let r1 = run(&d, &b1, &tail_opts(arm)).unwrap();
    assert_eq!(r1.end_epoch, e0 + 1);
    assert!(r1.arm.ends_with("+tail"));
    if pre {
        assert!(r1.docs_placed_hole > 0 && r1.docs_placed_hole <= n_pre as u64, "{r1:?}");
    } else {
        assert_eq!(r1.docs_placed_hole, 0, "no hole exists before the first batch");
    }
    assert!(r1.docs_placed_tail > 0, "{r1:?}");
    assert_eq!(r1.docs_placed, r1.docs_offered - r1.docs_unplaced_no_posting, "+tail places every doc with a surviving posting: {r1:?}");
    assert_eq!(r1.docs_unplaced_no_hole, 0);
    assert_eq!(r1.tail_rows_after, r1.docs_placed_tail);
    assert!(r1.tail_words_after > 0 && r1.tail_words_after <= p.tail_words);
    assert!(r1.phases[0].tail_records_written == r1.docs_placed_tail);
    let v = assert_verified(&d);
    assert_eq!((v.tail_words, v.tail_rows), (r1.tail_words_after, r1.tail_rows_after));
    assert!(v.tail_visible_postings > 0);
    model_checks(&d, &b1, &before, p.cap);
    let live1 = apply_model(&base, &b1);
    {
        let sh = Shard::open(&d).unwrap();
        assert_eq!(results(&sh, e0 + 1, &qs), reference_hits(&sh, e0 + 1, &live1, &qs), "{name}: epoch-{} search != clean reference", e0 + 1);
        assert_eq!(results(&sh, e0, &qs), reference_hits(&sh, e0, &base, &qs), "{name}: epoch-{e0} view changed");
        let tail_docs = (0..sh.n_rows()).filter(|&r| r >= sh.n_docs).count();
        assert_eq!(tail_docs as u64, r1.tail_rows_after);
    }
    // batch 2: deletes some tail docs and base docs, updates tail docs, inserts
    let before2 = visible_ids(&Shard::open(&d).unwrap(), e0 + 1);
    let tail_ids: Base = live1.iter().filter(|x| x.0 >= 900_000_000).cloned().collect();
    let mut b2 = make_batch(&tail_ids, p.dim, 2, 8, 8, 0, 0);
    b2.extend(make_batch(&live1.iter().filter(|x| x.0 < 900_000_000).cloned().collect(), p.dim, 3, 30, 50, 30, 10_000));
    let r2 = run(&d, &b2, &tail_opts(arm)).unwrap();
    assert_eq!(r2.end_epoch, e0 + 2);
    assert!(r2.docs_placed_hole > 0, "batch 2 must reuse batch 1's holes: {r2:?}");
    assert_eq!(r2.docs_placed, r2.docs_offered - r2.docs_unplaced_no_posting);
    assert!(r2.tail_rows_after >= r2.tail_rows_before);
    assert_verified(&d);
    model_checks(&d, &b2, &before2, p.cap);
    let live2 = apply_model(&live1, &b2);
    {
        let sh = Shard::open(&d).unwrap();
        assert_eq!(results(&sh, e0 + 2, &qs), reference_hits(&sh, e0 + 2, &live2, &qs), "{name}: epoch-{} search != clean reference", e0 + 2);
    }
    // batch 3: only inserts of small vectors; must land in holes (incl. tail-row holes) before the tail
    let before3 = visible_ids(&Shard::open(&d).unwrap(), e0 + 2);
    let b3 = make_batch(&live2, p.dim, 4, 0, 0, 12, 20_000);
    let r3 = run(&d, &b3, &tail_opts(arm)).unwrap();
    assert!(r3.docs_placed_hole > 0, "{r3:?}");
    assert_verified(&d);
    model_checks(&d, &b3, &before3, p.cap);
    let live3 = apply_model(&live2, &b3);
    let sh = Shard::open(&d).unwrap();
    assert_eq!(results(&sh, e0 + 3, &qs), reference_hits(&sh, e0 + 3, &live3, &qs), "{name}: epoch-{} search != clean reference", e0 + 3);
    // a tail-row hole was reused iff some placed doc sits at a tail row without being tail-appended
    let reused_tail_rows = (sh.n_docs..sh.n_rows()).filter(|&r| {
        let id = sh.ext_id(r);
        b3.iter().any(|x| x.id == id)
    }).count() as u64;
    println!("{name}: r1 tail {} / r2 hole {} tail {} / r3 hole {} tail {} (reused tail rows {reused_tail_rows})", r1.docs_placed_tail, r2.docs_placed_hole, r2.docs_placed_tail, r3.docs_placed_hole, r3.docs_placed_tail);
    if arm == Arm::A2 {
        assert_eq!(r1.postings_evicted + r2.postings_evicted + r3.postings_evicted, 0, "A2 never evicts");
    }
}

#[test]
fn t_tail_a2() {
    tail_arm("t_tail_a2", Arm::A2, true);
}

#[test]
fn t_tail_a2b() {
    tail_arm("t_tail_a2b", Arm::A2b, false);
}

/// The frozen A2 rule survives `+tail`: on a fresh copy no slot is dead, so
/// every offered posting is dropped for capacity and no record is written,
/// tail or not. `+tail` only removes the forward-record obstacle.
#[test]
fn t_tail_a2_fresh_copy_still_places_zero() {
    let p = params();
    let (d, base) = fresh("t_tail_a2_fresh", &p);
    let b = make_batch(&base, p.dim, 1, 60, 120, 40, 0);
    let r = run(&d, &b, &tail_opts(Arm::A2)).unwrap();
    assert_eq!((r.docs_placed, r.docs_placed_tail, r.docs_unplaced_no_posting), (0, 0, 160), "{r:?}");
    assert_eq!(r.postings_dropped_capacity, r.postings_offered);
    assert_eq!((r.tail_words_after, r.tail_rows_after), (0, 0));
    assert_verified(&d);
}

#[test]
fn t_tail_two_phase() {
    for (name, arm) in [("t_tail_2p_a2_free", Arm::A2TwoPhase { old_at_fill: false }), ("t_tail_2p_a2b_fill", Arm::A2bTwoPhase { old_at_fill: true })] {
        let p = params();
        let (d, base) = fresh(name, &p);
        let before = visible_ids(&Shard::open(&d).unwrap(), 0);
        let (n_del, n_upd, n_ins) = (20, 60, 200);
        let b = make_batch(&base, p.dim, 3, n_del, n_upd, n_ins, 0);
        let r = run(&d, &b, &tail_opts(arm)).unwrap();
        assert_eq!(r.end_epoch, 2);
        assert_eq!(r.docs_placed, r.docs_offered - r.docs_unplaced_no_posting, "{r:?}");
        assert!(r.docs_placed_hole > 0 && r.docs_placed_tail > 0, "{r:?}");
        if arm.old_at_fill() {
            assert!(r.docs_placed_hole <= n_del as u64, "old-at-fill: only true deletions are supply for this batch: {r:?}");
        } else {
            assert!(r.docs_placed_hole > n_del as u64, "old-at-free: updated-old rows are supply too: {r:?}");
        }
        // the FREE flip must publish the old tail counters, the FILL flip the new ones
        assert_eq!(r.tail_rows_before, 0);
        assert!(r.tail_rows_after == r.docs_placed_tail);
        assert_verified(&d);
        model_checks(&d, &b, &before, p.cap);
        let sh = Shard::open(&d).unwrap();
        let qs = queries(p.dim, 12, 8);
        let live = apply_model(&base, &b);
        assert_eq!(results(&sh, 2, &qs), reference_hits(&sh, 2, &live, &qs), "{name}: epoch-2 search != clean reference");
        let at1 = visible_ids(&sh, 1);
        let new_ids: Vec<u64> = b.iter().filter(|x| x.op == OP_UPSERT && x.id >= 900_000_000).map(|x| x.id).collect();
        assert!(new_ids.iter().all(|id| !at1.iter().any(|s| s.contains(id))), "tail docs must be invisible at e+1");
    }
}

#[test]
fn t_tail_reserve_exhaustion_refused() {
    let p = SynthParams { tail_words: 96, tail_rows: 3, ..params() };
    let (d, base) = fresh("t_tail_exhaust", &p);
    let h0 = file_hashes(&d);
    let b = make_batch(&base, p.dim, 5, 0, 0, 40, 0);
    let refuse = |d: &Path, b: &[Rec], arm: Arm, e: u64| {
        let mut sh = Shard::open(d).unwrap();
        let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
        let r = run_batch(&mut sh, b, &tail_opts(arm), table);
        let msg = match r {
            Err(Error::Msg(m)) => m,
            other => panic!("expected the exhaustion refusal, got {other:?}"),
        };
        assert!(msg.contains("forward tail exhausted"), "{msg}");
        assert_eq!(sh.wlog.n_ops, 0, "refused before any write");
        assert_eq!(sh.epoch(), e);
    };
    refuse(&d, &b, Arm::A2b, 0);
    refuse(&d, &b, Arm::A2TwoPhase { old_at_fill: false }, 0);
    assert_eq!(file_hashes(&d), h0, "no file changed");
    // A2 one flip on a fresh copy takes no posting, so nothing reaches the tail; after a
    // delete-only batch (5 holes, dead slots) the same 40 inserts overflow the reserve
    let r = run(&d, &b, &tail_opts(Arm::A2)).unwrap();
    assert_eq!((r.docs_placed, r.docs_unplaced_no_posting), (0, 40));
    let b0 = make_batch(&base, p.dim, 9, 5, 0, 0, 0);
    run(&d, &b0, &Opts { arm: Arm::A2, ..Default::default() }).unwrap();
    let h2 = file_hashes(&d);
    refuse(&d, &b, Arm::A2, 2);
    assert_eq!(file_hashes(&d), h2, "no file changed");
    // without +tail the same batch is accepted: at most the 5 holes are filled
    let r = run(&d, &b, &Opts { arm: Arm::A2, ..Default::default() }).unwrap();
    assert!(r.docs_placed <= 5 && r.docs_unplaced_no_hole >= 35, "{r:?}");
    assert_verified(&d);
    // a batch that fits the tiny reserve is accepted
    let live = apply_model(&apply_model(&base, &b0), &b);
    let b2 = make_batch(&live, p.dim, 6, 0, 0, 2, 100);
    let r2 = run(&d, &b2, &tail_opts(Arm::A2)).unwrap();
    assert!(r2.docs_placed >= 1 && r2.docs_placed_tail == r2.docs_placed, "{r2:?}");
    assert_verified(&d);
}

fn r1_tail_case(name: &str, arm: Arm, frac: f64, at_header: Option<bool>) {
    let p = params();
    let (d, base0) = fresh(name, &p);
    let e0 = if arm == Arm::A2 { 1 } else { 0 };
    let base = if arm == Arm::A2 {
        let b0 = make_batch(&base0, p.dim, 20, 40, 0, 0, 0);
        run(&d, &b0, &Opts { arm, ..Default::default() }).unwrap();
        apply_model(&base0, &b0)
    } else {
        base0
    };
    let bx = make_batch(&base, p.dim, 21, 70, 120, 30, 0);
    let probe = root().join(format!("{name}_probe"));
    copy_dir(&d, &probe);
    let log = root().join(format!("{name}.ops"));
    let mut sh = Shard::open(&probe).unwrap();
    sh.wlog.log = Some(std::io::BufWriter::new(std::fs::File::create(&log).unwrap()));
    let table = Arc::new(Table::open(&probe.join("readers.bin")).unwrap());
    let full = run_batch(&mut sh, &bx, &tail_opts(arm), table).unwrap();
    sh.flush_log().unwrap();
    assert!(full.docs_placed_tail > 0);
    drop(sh);
    let ops = load_ops(&log).unwrap();
    let crash_at = match at_header {
        None => ((full.write_ops as f64) * frac) as u64,
        Some(false) => ops.iter().position(|o| o.kind == OP_WRITE && o.file == F::Hdr as u8).unwrap() as u64,
        Some(true) => ops.iter().position(|o| o.kind == OP_SYNC && o.file == F::Hdr as u8).unwrap() as u64 + 1,
    };
    let mut sh = Shard::open(&d).unwrap();
    sh.wlog.crash_after = Some(crash_at);
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let r = run_batch(&mut sh, &bx, &tail_opts(arm), table);
    if crash_at >= ops.len() as u64 {
        // the header sync is the batch's last op: "crash after it" = a completed batch
        assert!(r.is_ok(), "{r:?}");
    } else {
        assert!(matches!(r, Err(Error::Injected(_))), "expected injected crash at {crash_at}/{}", ops.len());
    }
    drop(sh);
    let sh = Shard::open(&d).unwrap();
    let e_crash = sh.epoch();
    if let Some(after) = at_header {
        assert_eq!(e_crash, e0 + after as u64, "crash {} the header sync", if after { "after" } else { "before" });
    }
    if e_crash == e0 {
        assert_eq!((sh.tail_words, sh.tail_rows), (0, 0), "unpublished tail must stay unpublished");
    } else {
        assert_eq!((sh.tail_words, sh.tail_rows), (full.tail_words_after, full.tail_rows_after));
    }
    let before = visible_ids(&sh, e_crash);
    drop(sh);
    let mut sh = Shard::open(&d).unwrap();
    let rec = recover(&mut sh, None).unwrap();
    drop(sh);
    assert_verified(&d);
    let used: HashSet<u64> = bx.iter().map(|r| r.id).collect();
    let rest: Base = base.iter().filter(|x| !used.contains(&x.0)).cloned().collect();
    let by = make_batch(&rest, p.dim, 22, 10, 20, 80, 50_000);
    let ry = run(&d, &by, &tail_opts(arm)).unwrap();
    assert!(ry.docs_placed > 0 && (e_crash > e0 || ry.docs_placed_tail > 0), "{ry:?}");
    assert_verified(&d);
    let sh = Shard::open(&d).unwrap();
    let e = sh.epoch();
    let vis = visible_ids(&sh, e);
    let x_new: HashSet<u64> = bx.iter().filter(|r| r.op == OP_UPSERT && r.id >= 900_000_000).map(|r| r.id).collect();
    for (t, s) in vis.iter().enumerate() {
        for id in s {
            assert!(e_crash == e0 + 1 || !x_new.contains(id), "R1: aborted batch X's tail insert {id} visible in list {t} after batch Y");
        }
    }
    if e_crash == e0 {
        let x_del: HashSet<u64> = bx.iter().filter(|r| r.op == OP_DELETE).map(|r| r.id).collect();
        let base_vis: HashSet<u64> = before.iter().flatten().copied().collect();
        let now_vis: HashSet<u64> = vis.iter().flatten().copied().collect();
        for id in &x_del {
            if base_vis.contains(id) && !by.iter().any(|r| r.id == *id) {
                assert!(now_vis.contains(id), "R1: aborted delete of {id} took effect");
            }
        }
        // Y's tail rows start at the published bump (0): X's unpublished tail bytes were overwritten
        assert_eq!(ry.tail_rows_before, 0);
    }
    println!("{name} crash_at {crash_at}/{} e_crash {e_crash} recovery {:?}", full.write_ops, rec);
}

#[test]
fn t_tail_r1_aborted_then_different_batch() {
    for (i, frac) in [0.15, 0.4, 0.6, 0.85, 0.99].iter().enumerate() {
        r1_tail_case(&format!("t_tail_r1_a2_{i}"), Arm::A2, *frac, None);
        r1_tail_case(&format!("t_tail_r1_a2b_{i}"), Arm::A2b, *frac, None);
    }
    r1_tail_case("t_tail_r1_a2_hdr0", Arm::A2, 0.0, Some(false));
    r1_tail_case("t_tail_r1_a2_hdr1", Arm::A2, 0.0, Some(true));
    r1_tail_case("t_tail_r1_a2b_hdr0", Arm::A2b, 0.0, Some(false));
    r1_tail_case("t_tail_r1_a2b_hdr1", Arm::A2b, 0.0, Some(true));
}

#[test]
fn t_tail_power_loss_replay_and_restore() {
    let p = params();
    for (ai, arm) in [Arm::A2, Arm::A2b, Arm::A2TwoPhase { old_at_fill: false }].into_iter().enumerate() {
        let (pristine, base0) = fresh(&format!("t_tail_pl_pristine_{ai}"), &p);
        let base = if arm == Arm::A2 {
            let b0 = make_batch(&base0, p.dim, 60, 20, 0, 0, 0);
            run(&pristine, &b0, &Opts { arm, ..Default::default() }).unwrap();
            apply_model(&base0, &b0)
        } else {
            base0
        };
        let e0 = Shard::open(&pristine).unwrap().epoch();
        let qs = queries(p.dim, 10, 77);
        let mut refs: Vec<Vec<Vec<Hit>>> = {
            let sh = Shard::open(&pristine).unwrap();
            (0..=e0).map(|e| results(&sh, e, &qs)).collect()
        };
        let rec_dir = root().join(format!("t_tail_pl_rec_{ai}"));
        copy_dir(&pristine, &rec_dir);
        let log = root().join(format!("t_tail_pl_{ai}.ops"));
        let b = make_batch(&base, p.dim, 61, 20, 40, 150, 0);
        let mut sh = Shard::open(&rec_dir).unwrap();
        sh.wlog.log = Some(std::io::BufWriter::new(std::fs::File::create(&log).unwrap()));
        let table = Arc::new(Table::open(&rec_dir.join("readers.bin")).unwrap());
        let r = run_batch(&mut sh, &b, &tail_opts(arm), table).unwrap();
        sh.flush_log().unwrap();
        assert!(r.docs_placed_tail > 0, "{r:?}");
        for ep in e0 + 1..=r.end_epoch {
            refs.push(results(&sh, ep, &qs));
        }
        drop(sh);
        let ops = load_ops(&log).unwrap();
        let hdr_syncs: Vec<usize> = ops.iter().enumerate().filter(|(_, o)| o.kind == OP_SYNC && o.file == F::Hdr as u8).map(|(i, _)| i).collect();
        let work = root().join(format!("t_tail_pl_work_{ai}"));
        copy_dir(&pristine, &work);
        // restore after a full apply must bring every file back byte for byte
        // (tail ranges of forward_data / forward_offsets / row_id_override, the
        // header, posting_free.bin and forward_free.bin included)
        materialize(&work, &ops, ops.len(), false, 0).unwrap();
        assert_ne!(file_hashes(&work), file_hashes(&pristine));
        restore(&work, &pristine, &ops).unwrap();
        assert_eq!(file_hashes(&work), file_hashes(&pristine), "restore did not reproduce the pristine copy");
        let mut rng = ChaCha8Rng::seed_from_u64(99);
        let mut fails = Vec::new();
        for model in ["drop", "pages"] {
            for trial in 0..100 {
                let cut = rng.random_range(0..=ops.len());
                restore(&work, &pristine, &ops).unwrap();
                materialize(&work, &ops, cut, model == "pages", 1000 + trial).unwrap();
                let sh = Shard::open(&work).unwrap();
                let e = sh.epoch();
                let flips_done = e0 + hdr_syncs.iter().filter(|&&i| i < cut).count() as u64;
                let a_ok = if model == "drop" { e == flips_done } else { e <= flips_done + 1 && e >= e0 };
                let got = results(&sh, e, &qs);
                let b_ok = got == refs[e as usize];
                drop(sh);
                let mut sh = Shard::open(&work).unwrap();
                recover(&mut sh, None).unwrap();
                let v = verify(&sh, true).unwrap();
                if !(a_ok && b_ok && v.ok()) {
                    fails.push(format!("{model} cut {cut}/{}: epoch {e} flips {flips_done} a={a_ok} b={b_ok} verify={:?}", ops.len(), v.violations));
                }
            }
        }
        assert!(fails.is_empty(), "power-loss failures ({:?}+tail): {:#?}", arm, fails);
    }
}

#[test]
fn t_tail_verify_catches_bad_counters() {
    let p = params();
    let (d, base) = fresh("t_tail_verify", &p);
    let b = make_batch(&base, p.dim, 7, 20, 30, 20, 0);
    let r = run(&d, &b, &tail_opts(Arm::A2b)).unwrap();
    assert!(r.tail_rows_after > 1);
    // publish one tail row fewer: a visible posting now points beyond the published tail
    let mut sh = Shard::open(&d).unwrap();
    sh.write_header(2, r.heap_bytes_after, r.tail_words_after - 1, r.tail_rows_after - 1).unwrap();
    let v = verify(&sh, false).unwrap();
    assert!(!v.ok());
    assert!(v.violations.iter().any(|m| m.starts_with("I2") || m.starts_with("TAIL")), "{:?}", v.violations);
    assert!(sh.write_header(3, 0, p.tail_words + 1, 0).is_err(), "counters beyond the reserve are refused");
}

// -------------------------------------------------------------- heap reuse

/// Batches until the A2b heap refuses an epoch (cap `max`); every accepted
/// batch is verified. Returns (accepted batches, reports).
fn batches_to_exhaustion(d: &Path, base: &Base, dim: usize, reuse: bool, max: usize, tail: bool) -> (usize, Vec<Report>) {
    let mut live = base.clone();
    let mut reps = Vec::new();
    for k in 0..max {
        let b = make_batch(&live, dim, 100 + k as u64, live.len() / 15, live.len() / 8, live.len() / 30, 1000 * k as u64);
        let opts = Opts { arm: Arm::A2b, heap_reuse: reuse, tail, ..Default::default() };
        match run(d, &b, &opts) {
            Ok(r) => {
                assert_verified(d);
                live = apply_model(&live, &b);
                reps.push(r);
            }
            Err(Error::Msg(m)) => {
                assert!(m.contains("posting heap exhausted"), "{m}");
                let sh = Shard::open(d).unwrap();
                assert_eq!(sh.epoch(), k as u64, "refused epoch must not be published");
                assert_eq!(sh.wlog.n_ops, 0);
                return (k, reps);
            }
            Err(e) => panic!("{e}"),
        }
    }
    (max, reps)
}

#[test]
fn t_heap_reuse_extends_life() {
    let p = SynthParams { heap_factor: 3, ..params() };
    let (d0, base) = fresh("t_heap_off", &p);
    let d1 = root().join("t_heap_on");
    copy_dir(&d0, &d1);
    let (k_off, r_off) = batches_to_exhaustion(&d0, &base, p.dim, false, 30, false);
    let (k_on, r_on) = batches_to_exhaustion(&d1, &base, p.dim, true, 30, false);
    println!("SYNTHETIC batches to exhaustion (heap 3x): reuse off {k_off}, reuse on {k_on}");
    assert!(k_off < 30 && k_off >= 2, "expected the 3x reserve to exhaust without reuse: {k_off}");
    assert!(k_on >= 2 * k_off, "reuse must at least double the batches to exhaustion ({k_off} -> {k_on})");
    assert!(r_off.iter().all(|r| r.heap_reused_bytes == 0));
    assert_eq!(r_on[0].heap_reused_bytes, 0, "nothing to reuse on the first batch");
    assert_eq!(r_on[1].heap_reused_bytes, 0, "batch 1 superseded native lists only");
    assert!(r_on[2].heap_reused_bytes > 0, "batch 3 must reuse units superseded at epoch 2: {:?}", r_on[2]);
    for r in &r_on[1..] {
        assert!(r.heap_superseded_bytes > 0);
        assert!(r.heap_free_bytes_after > 0);
    }
    // the free list after the last accepted batch is exactly what a scan rebuilds
    let sh = Shard::open(&d1).unwrap();
    let pf = sh.read_posting_free().unwrap();
    let e = sh.epoch();
    let scan = inplace_updater::apply::rebuild_heap_free(&sh, (e & 1) as usize, sh.published().unwrap().bump, e).unwrap();
    let a: Vec<(u64, u64)> = pf.entries.iter().map(|x| (x.off, x.len)).collect();
    let b: Vec<(u64, u64)> = scan.entries.iter().map(|x| (x.off, x.len)).collect();
    assert_eq!(a, b, "trusted free list extents != scan (leak or overlap)");
    assert!(pf.entries.iter().all(|x| x.epoch <= e));
}

#[test]
fn t_heap_reuse_two_phase_and_tail() {
    let p = SynthParams { heap_factor: 3, ..params() };
    let (d, base) = fresh("t_heap_2p", &p);
    let b = make_batch(&base, p.dim, 31, 60, 100, 30, 0);
    let r = run(&d, &b, &Opts { arm: Arm::A2bTwoPhase { old_at_fill: false }, tail: true, ..Default::default() }).unwrap();
    assert_eq!(r.end_epoch, 2);
    // the FREE-epoch units are superseded by the FILL epoch (stamped 2)
    assert!(r.phases[1].heap_superseded_bytes > 0);
    assert_eq!(r.phases[1].heap_reused_bytes, 0, "units freed at 2 are not reusable at 2");
    assert_verified(&d);
    let sh = Shard::open(&d).unwrap();
    let pf = sh.read_posting_free().unwrap();
    assert!(pf.entries.iter().all(|x| x.epoch == 2));
    drop(sh);
    // the next batch (e_pub = 2) may reuse them
    let live = apply_model(&base, &b);
    let b2 = make_batch(&live, p.dim, 32, 40, 80, 20, 100);
    let r2 = run(&d, &b2, &Opts { arm: Arm::A2b, tail: true, ..Default::default() }).unwrap();
    assert!(r2.heap_reused_bytes > 0, "{r2:?}");
    assert_eq!(r2.docs_placed, r2.docs_offered - r2.docs_unplaced_no_posting);
    assert_verified(&d);
}

#[test]
fn t_heap_free_rebuild_after_crash() {
    let p = SynthParams { heap_factor: 3, ..params() };
    let (d, base) = fresh("t_heap_crash", &p);
    let b1 = make_batch(&base, p.dim, 41, 60, 100, 20, 0);
    run(&d, &b1, &Opts { arm: Arm::A2b, ..Default::default() }).unwrap();
    let live = apply_model(&base, &b1);
    let b2 = make_batch(&live, p.dim, 42, 60, 100, 20, 100);
    // record batch 2 on a probe to find the posting_free.bin replace op
    let probe = root().join("t_heap_crash_probe");
    copy_dir(&d, &probe);
    let log = root().join("t_heap_crash.ops");
    let mut sh = Shard::open(&probe).unwrap();
    sh.wlog.log = Some(std::io::BufWriter::new(std::fs::File::create(&log).unwrap()));
    let table = Arc::new(Table::open(&probe.join("readers.bin")).unwrap());
    run_batch(&mut sh, &b2, &Opts { arm: Arm::A2b, ..Default::default() }, table).unwrap();
    sh.flush_log().unwrap();
    drop(sh);
    let ops = load_ops(&log).unwrap();
    let pf_new = ops.iter().position(|o| o.kind == OP_NEWFILE && o.name == "posting_free.bin.next").unwrap();
    // ops: NEWFILE(.next) at pf_new, RENAME at +1, DIRSYNC at +2; a crash after the
    // NEWFILE alone leaves the old file (trusted), after the rename the new one (rebuilt)
    for (k, (crash_at, rebuilt)) in [(pf_new + 1, false), (pf_new + 2, true), (pf_new + 3, true)].into_iter().enumerate() {
        let w = root().join(format!("t_heap_crash_w{k}"));
        copy_dir(&d, &w);
        let mut sh = Shard::open(&w).unwrap();
        sh.wlog.crash_after = Some(crash_at as u64);
        let table = Arc::new(Table::open(&w.join("readers.bin")).unwrap());
        assert!(matches!(run_batch(&mut sh, &b2, &Opts { arm: Arm::A2b, ..Default::default() }, table), Err(Error::Injected(_))));
        assert_eq!(sh.epoch(), 1);
        sh.wlog.crash_after = None;
        let rec = recover(&mut sh, None).unwrap();
        assert_eq!(rec.posting_free_rebuilt, rebuilt, "crash at {crash_at}: a posting free list stamped 2 against E = 1 must be rebuilt by scan, an untouched one trusted: {rec:?}");
        drop(sh);
        assert_verified(&w);
        let r = run(&w, &b2, &Opts { arm: Arm::A2b, ..Default::default() }).unwrap();
        assert_eq!(r.end_epoch, 2);
        assert!(r.recovery.posting_free_trusted);
        assert_verified(&w);
        let live2 = apply_model(&live, &b2);
        let b3 = make_batch(&live2, p.dim, 43, 40, 60, 10, 200);
        let r3 = run(&w, &b3, &Opts { arm: Arm::A2b, ..Default::default() }).unwrap();
        assert!(r3.heap_reused_bytes > 0, "{r3:?}");
        assert_verified(&w);
    }
}

#[test]
fn t_heap_reuse_slow_reader_blocks() {
    let p = SynthParams { heap_factor: 3, ..params() };
    let (d, base) = fresh("t_heap_reader", &p);
    let b1 = make_batch(&base, p.dim, 51, 60, 100, 20, 0);
    run(&d, &b1, &Opts { arm: Arm::A2b, tail: true, ..Default::default() }).unwrap();
    let live1 = apply_model(&base, &b1);
    let b2 = make_batch(&live1, p.dim, 52, 60, 100, 20, 100);
    run(&d, &b2, &Opts { arm: Arm::A2b, tail: true, ..Default::default() }).unwrap();
    let live2 = apply_model(&live1, &b2);
    let qs = queries(p.dim, 6, 9);
    let ref2 = results(&Shard::open(&d).unwrap(), 2, &qs);
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let (d2, t2, qs2) = (d.clone(), table.clone(), queries(p.dim, 6, 9));
    let reader = std::thread::spawn(move || {
        let sh = Shard::open(&d2).unwrap();
        let g = ReaderGuard::claim(t2, 0, true).unwrap();
        let e = g.begin(|| sh.epoch()).unwrap();
        assert_eq!(e, 2);
        let mut out = Vec::new();
        for _ in 0..4 {
            for q in &qs2 {
                out.push(search_at(&sh, e, q, 20, Duration::from_millis(3), Some(&g)).unwrap());
            }
        }
        g.end().unwrap();
        out
    });
    std::thread::sleep(Duration::from_millis(200));
    // batch 3 (e_pub = 2) would reuse the units superseded at 2 that the reader at 2... may still read: no,
    // it reuses units superseded at <= 2; the reader at 2 never reads those. Batch 3 passes its gate.
    let b3 = make_batch(&live2, p.dim, 53, 40, 80, 10, 200);
    let r3 = run(&d, &b3, &Opts { arm: Arm::A2b, tail: true, ..Default::default() }).unwrap();
    assert!(r3.heap_reused_bytes > 0);
    // batch 4 (e_pub = 3) reuses units superseded at 3, which the reader at 2 reads: it must wait
    let live3 = apply_model(&live2, &b3);
    let b4 = make_batch(&live3, p.dim, 54, 40, 80, 10, 300);
    let r4 = run(&d, &b4, &Opts { arm: Arm::A2b, tail: true, ..Default::default() }).unwrap();
    let out = reader.join().unwrap();
    for (i, h) in out.iter().enumerate() {
        if h != &ref2[i % ref2.len()] {
            let sh = Shard::open(&d).unwrap();
            let now2 = search_at(&sh, 2, &qs[i % qs.len()], 20, Duration::ZERO, None).unwrap();
            panic!("slow reader at epoch 2 saw a changed result: pass {} query {}\nreader {:?}\nref    {:?}\nnow@2  {:?}\nr3 {:?}\nr4 {:?}", i / qs.len(), i % qs.len(), h, ref2[i % ref2.len()], now2, r3.phases[0], r4.phases[0]);
        }
    }
    assert!(r4.phases[0].wait_readers_s > 0.05 || r3.phases[0].wait_readers_s > 0.05, "a batch must have waited for the epoch-2 reader ({:?}, {:?})", r3.phases[0].wait_readers_s, r4.phases[0].wait_readers_s);
    assert!(r4.recovery.overrides_clear_deferred > 0, "batch 4's recovery must defer clearing overrides of rows the epoch-2 reader can still resolve: {:?}", r4.recovery);
    assert_verified(&d);
}
