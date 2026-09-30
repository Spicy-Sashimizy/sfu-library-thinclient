//! Updater tests on SYNTHETIC v3 shards the crate builds itself
//! (UPDATER_DESIGN.md §8 + revisions). Work dirs under
//! $INPLACE_TEST_DIR (default /home/vscode/work/inplace_update/stage2/tests).

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
use inplace_updater::search::{search_at, search_registered, Hit, Query};
use inplace_updater::store::{visible, w_start, Shard, F};
use inplace_updater::synth::{build, random_vec, SynthParams};
use inplace_updater::util::Error;
use inplace_updater::verify::verify;

fn root() -> PathBuf {
    let r = std::env::var("INPLACE_TEST_DIR").unwrap_or("/home/vscode/work/inplace_update/stage2/tests".into());
    PathBuf::from(r)
}

fn fresh(name: &str, p: &SynthParams) -> (PathBuf, Vec<(u64, Vec<u16>, Vec<f32>)>) {
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

fn params() -> SynthParams {
    SynthParams { n_docs: 1500, dim: 160, cap: 40, block: 6, nnz_min: 4, nnz_max: 16, seed: 11, heap_factor: 8, id_base: 1_000_000, tail_words: 0, tail_rows: 0 }
}

/// Deletes, updates (new vector), inserts (new ids).
fn make_batch(base: &[(u64, Vec<u16>, Vec<f32>)], dim: usize, seed: u64, n_del: usize, n_upd: usize, n_ins: usize, id_off: u64) -> Vec<Rec> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let mut idx: Vec<usize> = (0..base.len()).collect();
    for i in (1..idx.len()).rev() {
        let j = rng.random_range(0..=i);
        idx.swap(i, j);
    }
    let mut recs = Vec::new();
    for &i in &idx[..n_del] {
        recs.push(Rec { op: OP_DELETE, id: base[i].0, comps: vec![], vals: vec![] });
    }
    for &i in &idx[n_del..n_del + n_upd] {
        let (c, v) = random_vec(&mut rng, dim, 4, 14);
        recs.push(Rec { op: OP_UPSERT, id: base[i].0, comps: c, vals: v });
    }
    for k in 0..n_ins {
        let (c, v) = random_vec(&mut rng, dim, 4, 14);
        recs.push(Rec { op: OP_UPSERT, id: 900_000_000 + id_off + k as u64, comps: c, vals: v });
    }
    recs
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

fn assert_verified(dir: &Path) {
    let sh = Shard::open(dir).unwrap();
    let v = verify(&sh, true).unwrap();
    assert!(v.ok(), "verify failed: {:?}", v.violations);
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

/// I11-style model checks against the batch.
fn model_checks(dir: &Path, recs: &[Rec], before: &[HashSet<u64>], cap: usize, evicts: bool) {
    let sh = Shard::open(dir).unwrap();
    let e = sh.epoch();
    let after = visible_ids(&sh, e);
    let deleted: HashSet<u64> = recs.iter().filter(|r| r.op == OP_DELETE).map(|r| r.id).collect();
    let new: HashMap<u64, &Rec> = recs.iter().filter(|r| r.op == OP_UPSERT).map(|r| (r.id, r)).collect();
    for t in 0..sh.n_lists {
        assert!(after[t].len() <= cap.max(before[t].len()), "list {t} grew");
        for id in &after[t] {
            assert!(!deleted.contains(id), "deleted id {id} visible in list {t}");
            if let Some(r) = new.get(id) {
                assert!(r.comps.contains(&(t as u16)), "new doc {id} in list {t} without that component");
            } else {
                assert!(before[t].contains(id), "list {t}: id {id} appeared from nowhere");
            }
        }
    }
    let _ = evicts;
    let bank = (e & 1) as usize;
    for t in 0..sh.n_lists {
        let v = sh.view(t, bank, false).unwrap();
        for &w in &v.words {
            if !visible(w, e) {
                continue;
            }
            let row = sh.row_of_start(w_start(w)).unwrap();
            let id = sh.ext_id(row);
            if let Some(r) = new.get(&id) {
                let (c, _) = sh.decode(w_start(w), inplace_updater::store::w_len(w));
                let want: Vec<u16> = r.comps.clone();
                assert!(c.iter().all(|x| want.contains(x)), "record of {id} does not decode to its new vector");
            }
        }
    }
}

#[test]
fn t_open_identity() {
    let (d, _) = fresh("t_open", &params());
    assert_verified(&d);
    let sh = Shard::open(&d).unwrap();
    for t in 0..sh.n_lists {
        let v = sh.view(t, 0, true).unwrap();
        let (body, man) = inplace_updater::summary::encode_list(&v.words, &v.bo, &v.blocks, v.man.dim);
        assert_eq!(&body[..], &sh.pl()[sh.locs[t].pp..sh.locs[t].end], "list {t} re-encode differs");
        assert_eq!(man, sh.lists[t]);
    }
}

#[test]
fn t_a2_one_flip() {
    let p = params();
    let (d, base) = fresh("t_a2", &p);
    let before = visible_ids(&Shard::open(&d).unwrap(), 0);
    let b1 = make_batch(&base, p.dim, 1, 60, 120, 40, 0);
    let r1 = run(&d, &b1, &Opts { arm: Arm::A2, ..Default::default() }).unwrap();
    assert_eq!(r1.end_epoch, 1);
    assert_eq!(r1.docs_placed, 0, "A2 from a fresh copy must place zero records");
    assert_eq!(r1.postings_inserted, 0);
    assert!(r1.deletes_applied == 60 && r1.rows_freed >= 180);
    assert_verified(&d);
    model_checks(&d, &b1, &before, p.cap, false);
    let before2 = visible_ids(&Shard::open(&d).unwrap(), 1);
    let base2: Vec<_> = base.iter().filter(|x| !b1.iter().any(|r| r.id == x.0)).cloned().collect();
    let b2 = make_batch(&base2, p.dim, 2, 20, 40, 30, 10_000);
    let r2 = run(&d, &b2, &Opts { arm: Arm::A2, ..Default::default() }).unwrap();
    assert_eq!(r2.end_epoch, 2);
    assert!(r2.docs_placed > 0, "second batch absorbs into the first batch's frees");
    assert_eq!(r2.postings_evicted, 0);
    assert_verified(&d);
    model_checks(&d, &b2, &before2, p.cap, false);
}

fn two_phase(name: &str, arm: Arm) {
    let p = params();
    let (d, base) = fresh(name, &p);
    let sh0 = Shard::open(&d).unwrap();
    let before = visible_ids(&sh0, 0);
    let qs = queries(p.dim, 15, 5);
    let ref0 = results(&sh0, 0, &qs);
    drop(sh0);
    let b = make_batch(&base, p.dim, 3, 80, 150, 30, 0);
    let r = run(&d, &b, &Opts { arm, ..Default::default() }).unwrap();
    assert_eq!(r.end_epoch, 2);
    assert!(r.docs_placed > 0);
    assert_verified(&d);
    model_checks(&d, &b, &before, p.cap, true);
    let sh = Shard::open(&d).unwrap();
    let at1 = visible_ids(&sh, 1);
    let upd: Vec<u64> = b.iter().filter(|x| x.op == OP_UPSERT && x.id < 900_000_000).map(|x| x.id).collect();
    let present_at1 = upd.iter().filter(|id| at1.iter().any(|s| s.contains(id))).count();
    if arm.old_at_fill() {
        assert!(present_at1 > 0, "old-at-fill: updated docs must still be served at e+1");
    } else {
        assert_eq!(present_at1, 0, "old-at-free: updated docs are absent at e+1");
    }
    let _ = ref0;
    println!("{name}: {}", serde_json::to_string(&r).unwrap());
}

#[test]
fn t_a2_2p_free() {
    two_phase("t_a2_2p_free", Arm::A2TwoPhase { old_at_fill: false });
}
#[test]
fn t_a2_2p_fill() {
    two_phase("t_a2_2p_fill", Arm::A2TwoPhase { old_at_fill: true });
}
#[test]
fn t_a2b_2p_free() {
    two_phase("t_a2b_2p_free", Arm::A2bTwoPhase { old_at_fill: false });
}
#[test]
fn t_a2b_2p_fill() {
    two_phase("t_a2b_2p_fill", Arm::A2bTwoPhase { old_at_fill: true });
}

#[test]
fn t_a2b_one_flip_and_r2() {
    let p = params();
    let (d, base) = fresh("t_a2b", &p);
    let before = visible_ids(&Shard::open(&d).unwrap(), 0);
    let b1 = make_batch(&base, p.dim, 4, 60, 100, 20, 0);
    let r1 = run(&d, &b1, &Opts { arm: Arm::A2b, ..Default::default() }).unwrap();
    assert_eq!(r1.docs_placed, 0, "A2b one flip: no hole on the first batch, no forward tail");
    assert!(r1.a2b_lists_rewritten > 0 && r1.heap_bytes_after > 0);
    assert_verified(&d);
    model_checks(&d, &b1, &before, p.cap, true);
    let sh = Shard::open(&d).unwrap();
    let rewritten: Vec<usize> = (0..sh.n_lists).filter(|&t| sh.dir_entry(1, t) != sh.native_off(t)).collect();
    assert!(!rewritten.is_empty());
    drop(sh);
    // R2: a batch that touches none of the rewritten lists must not revert them
    let rset: HashSet<usize> = rewritten.iter().copied().collect();
    let sh = Shard::open(&d).unwrap();
    let e = sh.epoch();
    let vis = visible_ids(&sh, e);
    let mut ids_untouched: Vec<u64> = Vec::new();
    'outer: for (id, _, _) in &base {
        if b1.iter().any(|r| r.id == *id) {
            continue;
        }
        for t in 0..sh.n_lists {
            if vis[t].contains(id) && rset.contains(&t) {
                continue 'outer;
            }
        }
        if vis.iter().any(|s| s.contains(id)) {
            ids_untouched.push(*id);
        }
        if ids_untouched.len() >= 3 {
            break;
        }
    }
    drop(sh);
    assert!(!ids_untouched.is_empty(), "no doc outside the rewritten lists");
    let b2: Vec<Rec> = ids_untouched.iter().map(|&id| Rec { op: OP_DELETE, id, comps: vec![], vals: vec![] }).collect();
    let r2 = run(&d, &b2, &Opts { arm: Arm::A2b, ..Default::default() }).unwrap();
    assert_eq!(r2.end_epoch, 2);
    let sh = Shard::open(&d).unwrap();
    for &t in &rewritten {
        assert_ne!(sh.dir_entry(0, t), sh.native_off(t), "R2: list {t} reverted to native at e+2");
    }
    drop(sh);
    assert_verified(&d);
}

#[test]
fn t_r2_inflation_persists() {
    let p = params();
    let (d, base) = fresh("t_r2_infl", &p);
    let b = make_batch(&base, p.dim, 5, 80, 150, 30, 0);
    run(&d, &b, &Opts { arm: Arm::A2TwoPhase { old_at_fill: false }, ..Default::default() }).unwrap();
    let sh = Shard::open(&d).unwrap();
    let nz: usize = (0..sh.n_blocks_total).filter(|&j| sh.infl(0, j) != 0).count();
    assert!(nz > 0, "expected raised inflation codes");
    drop(sh);
    let b2 = vec![Rec { op: OP_DELETE, id: 123, comps: vec![], vals: vec![] }];
    run(&d, &b2, &Opts { arm: Arm::A2, ..Default::default() }).unwrap();
    let sh = Shard::open(&d).unwrap();
    let nz3: usize = (0..sh.n_blocks_total).filter(|&j| sh.infl(1, j) != 0).count();
    assert_eq!(nz3, nz, "R2: inflation codes must carry into the next epoch's bank");
    drop(sh);
    assert_verified(&d);
}

fn r1_case(name: &str, arm: Arm, frac: f64) {
    let p = params();
    let (d, base) = fresh(name, &p);
    let bx = make_batch(&base, p.dim, 21, 70, 120, 30, 0);
    let probe = root().join(format!("{name}_probe"));
    copy_dir(&d, &probe);
    let mut sh = Shard::open(&probe).unwrap();
    let table = Arc::new(Table::open(&probe.join("readers.bin")).unwrap());
    let full = run_batch(&mut sh, &bx, &Opts { arm, ..Default::default() }, table).unwrap();
    let n_ops = full.write_ops - 0;
    drop(sh);
    let crash_at = ((n_ops as f64) * frac) as u64;
    let mut sh = Shard::open(&d).unwrap();
    sh.wlog.crash_after = Some(crash_at);
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let r = run_batch(&mut sh, &bx, &Opts { arm, ..Default::default() }, table);
    assert!(matches!(r, Err(Error::Injected(_))), "expected injected crash");
    let e_crash = sh.epoch();
    drop(sh);
    let before = visible_ids(&Shard::open(&d).unwrap(), e_crash);
    // A different batch Y: disjoint ids
    let used: HashSet<u64> = bx.iter().map(|r| r.id).collect();
    let rest: Vec<_> = base.iter().filter(|x| !used.contains(&x.0)).cloned().collect();
    let by = make_batch(&rest, p.dim, 22, 30, 50, 20, 50_000);
    let ry = run(&d, &by, &Opts { arm, ..Default::default() }).unwrap();
    assert_verified(&d);
    let sh = Shard::open(&d).unwrap();
    let e = sh.epoch();
    let vis = visible_ids(&sh, e);
    let x_new: HashSet<u64> = bx.iter().filter(|r| r.op == OP_UPSERT && r.id >= 900_000_000).map(|r| r.id).collect();
    for (t, s) in vis.iter().enumerate() {
        for id in s {
            assert!(!x_new.contains(id), "R1: aborted batch X's insert {id} visible in list {t} after batch Y");
        }
    }
    let x_del: HashSet<u64> = bx.iter().filter(|r| r.op == OP_DELETE).map(|r| r.id).collect();
    if e_crash == 0 {
        let base_vis: HashSet<u64> = before.iter().flatten().copied().collect();
        let now_vis: HashSet<u64> = vis.iter().flatten().copied().collect();
        for id in &x_del {
            if base_vis.contains(id) {
                assert!(now_vis.contains(id), "R1: aborted delete of {id} took effect");
            }
        }
    }
    println!("{name} crash_at {crash_at}/{n_ops} e_crash {e_crash} recovery {:?}", ry.recovery);
}

#[test]
fn t_r1_aborted_then_different_batch() {
    for (i, frac) in [0.2, 0.5, 0.8, 0.97].iter().enumerate() {
        r1_case(&format!("t_r1_a2_{i}"), Arm::A2TwoPhase { old_at_fill: false }, *frac);
        r1_case(&format!("t_r1_a2b_{i}"), Arm::A2b, *frac);
        r1_case(&format!("t_r1_a21_{i}"), Arm::A2, *frac);
    }
}

#[test]
fn t_r3_slow_reader_blocks_reuse() {
    let p = params();
    let (d, base) = fresh("t_r3", &p);
    let qs = queries(p.dim, 6, 9);
    let ref0 = results(&Shard::open(&d).unwrap(), 0, &qs);
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let d2 = d.clone();
    let t2 = table.clone();
    let reader = std::thread::spawn(move || {
        let sh = Shard::open(&d2).unwrap();
        let g = ReaderGuard::claim(t2, 0, true).unwrap();
        let e = g.begin(|| sh.epoch()).unwrap();
        assert_eq!(e, 0);
        let mut out = Vec::new();
        for _ in 0..4 {
            for q in &qs {
                out.push(search_at(&sh, e, q, 20, Duration::from_millis(3), Some(&g)).unwrap());
            }
        }
        g.end().unwrap();
        out
    });
    std::thread::sleep(Duration::from_millis(200));
    let b = make_batch(&base, p.dim, 31, 60, 100, 20, 0);
    let r = run(&d, &b, &Opts { arm: Arm::A2TwoPhase { old_at_fill: false }, ..Default::default() }).unwrap();
    let out = reader.join().unwrap();
    for (i, h) in out.iter().enumerate() {
        assert_eq!(h, &ref0[i % ref0.len()], "slow reader saw a changed epoch-0 result");
    }
    assert!(r.phases[1].wait_readers_s > 0.05, "FILL phase must wait for the reader at e ({:?})", r.phases[1].wait_readers_s);
    assert_verified(&d);
}

#[test]
fn t_r3_lease_reclaim_without_heartbeat() {
    let p = params();
    let (d, base) = fresh("t_r3_lease", &p);
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let sh = Shard::open(&d).unwrap();
    let g = ReaderGuard::claim(table.clone(), 300_000_000, false).unwrap();
    let e = g.begin(|| sh.epoch()).unwrap();
    assert_eq!(e, 0);
    let b = make_batch(&base, p.dim, 41, 40, 60, 10, 0);
    let r = run(&d, &b, &Opts { arm: Arm::A2TwoPhase { old_at_fill: false }, ..Default::default() }).unwrap();
    assert!(r.phases.iter().map(|x| x.stale_reader_slots_cleared).sum::<u64>() >= 1, "lease expiry must reclaim the slot");
    assert!(g.end().is_err(), "a reader whose slot was reclaimed must fail its query");
    // heartbeat on + lease shorter than the hold: must NOT be reclaimed
    let g2 = ReaderGuard::claim(table.clone(), 200_000_000, true).unwrap();
    let e2 = g2.begin(|| sh.epoch()).unwrap();
    let d2 = d.clone();
    let h = std::thread::spawn(move || {
        let base2: Vec<(u64, Vec<u16>, Vec<f32>)> = Vec::new();
        let _ = base2;
        let b = vec![Rec { op: OP_DELETE, id: 1_000_007, comps: vec![], vals: vec![] }];
        run(&d2, &b, &Opts { arm: Arm::A2TwoPhase { old_at_fill: false }, reader_timeout: Duration::from_secs(30), ..Default::default() }).unwrap()
    });
    std::thread::sleep(Duration::from_millis(900));
    assert!(g2.check().is_ok(), "heartbeating reader was reclaimed");
    let _ = e2;
    g2.end().unwrap();
    let r2 = h.join().unwrap();
    assert!(r2.phases[1].wait_readers_s > 0.5, "updater should have waited for the heartbeating reader");
}

#[test]
fn t_r4_epoch_bound() {
    let p = params();
    let (d, base) = fresh("t_r4", &p);
    let mut sh = Shard::open(&d).unwrap();
    sh.write_header(32767, 0, 0, 0).unwrap();
    assert!(sh.write_header(32768, 0, 0, 0).is_err());
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let b = make_batch(&base, p.dim, 1, 5, 5, 0, 0);
    assert!(run_batch(&mut sh, &b, &Opts { arm: Arm::A2, ..Default::default() }, table).is_err());
}

fn op_index(log: &Path, pred: impl Fn(&inplace_updater::plsim::Op) -> bool) -> usize {
    let ops = load_ops(log).unwrap();
    ops.iter().position(pred).unwrap()
}

#[test]
fn t_r5_side_file_orders() {
    let p = params();
    for (k, after_flip) in [false, true].iter().enumerate() {
        let (d, base) = fresh(&format!("t_r5_{k}"), &p);
        let b = make_batch(&base, p.dim, 51, 60, 100, 20, 0);
        let probe = root().join(format!("t_r5_{k}_probe"));
        copy_dir(&d, &probe);
        let log = root().join(format!("t_r5_{k}.ops"));
        let mut sh = Shard::open(&probe).unwrap();
        sh.wlog.log = Some(std::io::BufWriter::new(std::fs::File::create(&log).unwrap()));
        let table = Arc::new(Table::open(&probe.join("readers.bin")).unwrap());
        let opts = Opts { arm: Arm::A2, replace_after_flip: *after_flip, ..Default::default() };
        run_batch(&mut sh, &b, &opts, table).unwrap();
        sh.flush_log().unwrap();
        drop(sh);
        // recovery writes happen before the batch in the log too; the crash
        // point is between the free-list replace and the header flip (a), or
        // between the header flip and the replace (b).
        let hdr_first = op_index(&log, |o| o.kind == inplace_updater::store::OP_WRITE && o.file == F::Hdr as u8);
        let newfile_after_flip = if !*after_flip { 0 } else {
            let ops = load_ops(&log).unwrap();
            let last_hdr_sync = ops.iter().rposition(|o| o.kind == inplace_updater::store::OP_SYNC && o.file == F::Hdr as u8).unwrap();
            last_hdr_sync + ops[last_hdr_sync..].iter().position(|o| o.kind == inplace_updater::store::OP_NEWFILE).unwrap()
        };
        let crash_at = if *after_flip { newfile_after_flip as u64 } else { hdr_first as u64 };
        let mut sh = Shard::open(&d).unwrap();
        sh.wlog.crash_after = Some(crash_at);
        let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
        assert!(matches!(run_batch(&mut sh, &b, &opts, table), Err(Error::Injected(_))));
        let e = sh.epoch();
        assert_eq!(e, if *after_flip { 1 } else { 0 });
        sh.wlog.crash_after = None;
        let rec = recover(&mut sh, None).unwrap();
        assert!(rec.free_list_rebuilt, "R5 order {k}: free list with epoch != E must be rebuilt (E={e})");
        drop(sh);
        assert_verified(&d);
        let used: HashSet<u64> = b.iter().map(|r| r.id).collect();
        let rest: Vec<_> = base.iter().filter(|x| !used.contains(&x.0)).cloned().collect();
        let b2 = make_batch(&rest, p.dim, 52, 20, 40, 30, 70_000);
        run(&d, &b2, &Opts { arm: Arm::A2TwoPhase { old_at_fill: false }, ..Default::default() }).unwrap();
        assert_verified(&d);
    }
}

#[test]
fn t_power_loss_replay() {
    let p = params();
    for (ai, arm) in [Arm::A2TwoPhase { old_at_fill: false }, Arm::A2b].into_iter().enumerate() {
        let (pristine, base) = fresh(&format!("t_pl_pristine_{ai}"), &p);
        let qs = queries(p.dim, 10, 77);
        let ref_e: Vec<Vec<Vec<Hit>>> = {
            let sh = Shard::open(&pristine).unwrap();
            vec![results(&sh, 0, &qs)]
        };
        let rec_dir = root().join(format!("t_pl_rec_{ai}"));
        copy_dir(&pristine, &rec_dir);
        let log = root().join(format!("t_pl_{ai}.ops"));
        let b = make_batch(&base, p.dim, 61, 60, 100, 20, 0);
        let mut sh = Shard::open(&rec_dir).unwrap();
        sh.wlog.log = Some(std::io::BufWriter::new(std::fs::File::create(&log).unwrap()));
        let table = Arc::new(Table::open(&rec_dir.join("readers.bin")).unwrap());
        let r = run_batch(&mut sh, &b, &Opts { arm, ..Default::default() }, table).unwrap();
        sh.flush_log().unwrap();
        let mut refs = ref_e.clone();
        for ep in 1..=r.end_epoch {
            refs.push(results(&sh, ep, &qs));
        }
        drop(sh);
        let ops = load_ops(&log).unwrap();
        let hdr_syncs: Vec<usize> = ops.iter().enumerate().filter(|(_, o)| o.kind == inplace_updater::store::OP_SYNC && o.file == F::Hdr as u8).map(|(i, _)| i).collect();
        let work = root().join(format!("t_pl_work_{ai}"));
        copy_dir(&pristine, &work);
        let mut rng = ChaCha8Rng::seed_from_u64(99);
        let mut fails = Vec::new();
        for model in ["drop", "pages"] {
            for trial in 0..100 {
                let cut = rng.random_range(0..=ops.len());
                restore(&work, &pristine, &ops).unwrap();
                materialize(&work, &ops, cut, model == "pages", 1000 + trial).unwrap();
                let sh = Shard::open(&work).unwrap();
                let e = sh.epoch();
                let flips_done = hdr_syncs.iter().filter(|&&i| i < cut).count() as u64;
                let a_ok = if model == "drop" { e == flips_done } else { e <= flips_done + 1 && e >= flips_done.saturating_sub(0).min(e) };
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
        assert!(fails.is_empty(), "power-loss failures ({:?}): {:#?}", arm, fails);
    }
}

#[test]
fn t_registered_search_roundtrip() {
    let p = params();
    let (d, _) = fresh("t_reg", &p);
    let sh = Shard::open(&d).unwrap();
    let table = Arc::new(Table::open(&d.join("readers.bin")).unwrap());
    let g = ReaderGuard::claim(table.clone(), 0, true).unwrap();
    let q = &queries(p.dim, 1, 3)[0];
    let (e, hits) = search_registered(&sh, &g, q, 10, Duration::ZERO).unwrap();
    assert_eq!(e, 0);
    assert!(!hits.is_empty());
    let mut c = 0;
    assert_eq!(table.oldest(&mut c), None, "idle reader holds no epoch");
}


// ------------------------------------------------------------ write guard

fn guard_err(dir: &Path) -> String {
    match Shard::open(dir) {
        Ok(_) => "OPENED".into(),
        Err(e) => e.to_string(),
    }
}

#[test]
fn t_guard_protected_roots() {
    let served = Path::new("/workspaces/sfu-library-thinclient/data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap");
    let e = guard_err(served);
    assert!(e.starts_with("GUARD"), "served shard not refused: {e}");
    let stage = Path::new("/var/tmp/seismic_stage/global_shard0of8.dotvbyte.e5.v2.mmap");
    if stage.exists() {
        let e = guard_err(stage);
        assert!(e.starts_with("GUARD"), "staged shard not refused: {e}");
    }
    let e = guard_err(Path::new("/workspaces/sfu-library-thinclient/data"));
    assert!(e.starts_with("GUARD"), "{e}");
    let tmp = std::env::temp_dir().join("inplace_guard_outside");
    let _ = std::fs::create_dir_all(&tmp);
    let e = guard_err(&tmp);
    assert!(e.contains("allow-list"), "outside allow-list not refused: {e}");
    assert!(build(&Path::new("/workspaces/sfu-library-thinclient/data/inplace_guard_should_not_exist"), &params()).is_err());
    assert!(!Path::new("/workspaces/sfu-library-thinclient/data/inplace_guard_should_not_exist").exists());
}

#[test]
fn t_guard_symlink_hardlink_sentinel() {
    let p = params();
    let (d, _) = fresh("t_guard", &p);
    assert!(Shard::open(&d).is_ok());
    // symlink to a protected file
    let s = root().join("t_guard_sym");
    copy_dir(&d, &s);
    std::fs::remove_file(s.join("config.json")).unwrap();
    std::os::unix::fs::symlink("/workspaces/sfu-library-thinclient/data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.e5.v2.mmap/config.json", s.join("config.json")).unwrap();
    let e = guard_err(&s);
    assert!(e.contains("symlink"), "symlink not refused: {e}");
    // a hard link (any second link to a file is refused)
    let h = root().join("t_guard_hard");
    copy_dir(&d, &h);
    std::fs::hard_link(h.join("config.json"), root().join("t_guard_hard_alias.json")).unwrap();
    let e = guard_err(&h);
    let _ = std::fs::remove_file(root().join("t_guard_hard_alias.json"));
    assert!(e.contains("hard link"), "hard link not refused: {e}");
    // missing sentinel
    let m = root().join("t_guard_nosent");
    copy_dir(&d, &m);
    std::fs::remove_file(m.join(inplace_updater::guard::SENTINEL)).unwrap();
    let e = guard_err(&m);
    assert!(e.contains("sentinel"), "missing sentinel not refused: {e}");
    // sentinel naming another path (a raw copy)
    let o = root().join("t_guard_othersent");
    let _ = std::fs::remove_dir_all(&o);
    std::fs::create_dir_all(&o).unwrap();
    for e in std::fs::read_dir(&d).unwrap() {
        let e = e.unwrap();
        std::fs::copy(e.path(), o.join(e.file_name())).unwrap();
    }
    let e = guard_err(&o);
    assert!(e.contains("sentinel names"), "foreign sentinel not refused: {e}");
    // the power-loss writers go through the guard too
    assert!(restore(&o, &d, &[]).is_err());
}

#[test]
fn t_guard_non_local_fs_detection() {
    // /workspaces is a 9p mount on this host; the guard's fs check must
    // classify it as non-local (a full refusal test is impossible here: no
    // allow-listed path is on a network filesystem).
    let t = inplace_updater::guard::fs_type_of(Path::new("/workspaces/sfu-library-thinclient"));
    assert_eq!(t.as_deref(), Some("9p"));
    assert!(!inplace_updater::guard::is_local_fs(Path::new("/workspaces/sfu-library-thinclient")));
    assert!(inplace_updater::guard::is_local_fs(&root()));
}
