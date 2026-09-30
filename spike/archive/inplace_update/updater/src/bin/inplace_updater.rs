//! CLI for the in-place updater. Every subcommand prints one JSON object.
//!
//!   synth    --out DIR [--docs N --dim D --cap C --block B --seed S --heap-factor H
//!            --tail-words W --tail-rows R]   (W/R > 0: a v3.1 shard with a forward tail reserve)
//!   synth-batch --dir DIR --out FILE [--seed S --n-del D --n-upd U --n-ins I --id-off O]
//!            (a batch over the shard's live ids: deletes, updates, inserts of fresh ids)
//!   apply    --dir DIR --batch FILE --arm a2|a2-2p-free|a2-2p-fill|a2b|a2b-2p-free|a2b-2p-fill[-tail]
//!            [--tail] [--heap-reuse 0|1 (default 1)]
//!            [--op-log FILE] [--crash-after-op N] [--reader-timeout-s S]
//!            [--hybrid-min-slots N] [--hold-between-flips-ms MS] [--report FILE]
//!   recover  --dir DIR
//!   verify   --dir DIR [--deep]
//!   search   --dir DIR --queries FILE --k K [--epoch E] [--loop-s S] [--sleep-ms MS]
//!            [--no-heartbeat] [--lease-ms MS] [--out FILE]
//!   crash    --dir WORK --log FILE --cut C --model drop|pages --seed S
//!   restore  --dir WORK --pristine DIR --log FILE
//!   nops     --log FILE
//!   sentinel --dir DIR --source-fnv HEX     (write the work-copy sentinel; guard-checked)
//!   guard-check --dir DIR
//!   identity --dir DIR [--lists N]          (A2b re-encode reproduces native bytes)
//!   identity-v2 --dir DIR [--lists N]       (same on a dv-v2 dir, read-only)

use std::collections::HashMap;
use std::fs::File;
use std::io::BufWriter;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use inplace_updater::apply::{recover, run_batch, scan_rows, Arm, Opts};
use inplace_updater::batch::{read_batch, write_batch, Rec, OP_DELETE, OP_UPSERT};
use inplace_updater::layout::{walk, ListManifest};
use inplace_updater::plsim::{load_ops, materialize, restore};
use inplace_updater::readers::{ReaderGuard, Table};
use inplace_updater::search::{search_at, search_registered, Query};
use inplace_updater::store::Shard;
use inplace_updater::summary::{decode_summary, encode_list};
use inplace_updater::synth::{build, random_vec, SynthParams};
use inplace_updater::verify::verify;
use inplace_updater::util::{Error, Result};

fn args() -> (String, HashMap<String, String>) {
    let a: Vec<String> = std::env::args().collect();
    let cmd = a.get(1).cloned().unwrap_or_default();
    let mut m = HashMap::new();
    let mut i = 2;
    while i < a.len() {
        let k = a[i].trim_start_matches("--").to_string();
        if i + 1 < a.len() && !a[i + 1].starts_with("--") {
            m.insert(k, a[i + 1].clone());
            i += 2;
        } else {
            m.insert(k, "1".into());
            i += 1;
        }
    }
    (cmd, m)
}

fn get<T: std::str::FromStr>(m: &HashMap<String, String>, k: &str, d: T) -> T {
    m.get(k).and_then(|v| v.parse().ok()).unwrap_or(d)
}

fn req(m: &HashMap<String, String>, k: &str) -> Result<String> {
    m.get(k).cloned().ok_or_else(|| Error::Msg(format!("--{k} required")))
}

fn load_queries(path: &str) -> Result<Vec<(String, Query)>> {
    let v: serde_json::Value = serde_json::from_slice(&std::fs::read(path)?)?;
    let mut out = Vec::new();
    for q in v.as_array().ok_or_else(|| Error::Msg("queries: expected a list".into()))? {
        let id = q["id"].as_str().map(|s| s.to_string()).unwrap_or_else(|| q["id"].to_string());
        let comps: Vec<u16> = q["comps"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as u16).collect();
        let vals: Vec<f32> = q["vals"].as_array().unwrap().iter().map(|x| x.as_f64().unwrap() as f32).collect();
        let mut pairs: Vec<(u16, f32)> = comps.into_iter().zip(vals).collect();
        pairs.sort_by_key(|p| p.0);
        pairs.dedup_by_key(|p| p.0);
        let (comps, vals) = pairs.into_iter().unzip();
        out.push((id, Query { comps, vals }));
    }
    Ok(out)
}

fn identity(pl: &[u8], lists: &[ListManifest], n: usize) -> serde_json::Value {
    let locs = walk(lists);
    let mut ok = 0u64;
    let mut bad: Vec<usize> = Vec::new();
    let mut checked = 0u64;
    for t in 0..lists.len().min(n) {
        let m = &lists[t];
        let l = &locs[t];
        let words: &[u64] = bytemuck::cast_slice(&pl[l.pp..l.pp + 8 * m.packed_postings_words]);
        let bo: &[usize] = bytemuck::cast_slice(&pl[l.bo..l.bo + 8 * m.block_offsets_len]);
        let blocks = decode_summary(pl, l, m);
        let (body, man) = encode_list(words, bo, &blocks, m.dim);
        checked += 1;
        if &body[..] == &pl[l.pp..l.end] && &man == m {
            ok += 1;
        } else if bad.len() < 20 {
            bad.push(t);
        }
    }
    serde_json::json!({"lists_checked": checked, "identical": ok, "first_mismatches": bad})
}

fn run() -> Result<serde_json::Value> {
    let (cmd, m) = args();
    match cmd.as_str() {
        "synth" => {
            let p = SynthParams {
                n_docs: get(&m, "docs", 2000),
                dim: get(&m, "dim", 300),
                cap: get(&m, "cap", 60),
                block: get(&m, "block", 8),
                seed: get(&m, "seed", 7),
                heap_factor: get(&m, "heap-factor", 6),
                tail_words: get(&m, "tail-words", 0),
                tail_rows: get(&m, "tail-rows", 0),
                ..Default::default()
            };
            let out = PathBuf::from(req(&m, "out")?);
            let base = build(&out, &p)?;
            Ok(serde_json::json!({"out": out, "docs": base.len(), "label": "SYNTHETIC", "tail_words": p.tail_words, "tail_rows": p.tail_rows,
                                  "heap_factor": p.heap_factor}))
        }
        "synth-batch" => {
            use rand::{Rng, SeedableRng};
            let dir = PathBuf::from(req(&m, "dir")?);
            let sh = Shard::open(&dir)?;
            let e = sh.epoch();
            let rs = scan_rows(&sh, (e & 1) as usize, e)?;
            let mut live: Vec<u64> = (0..sh.n_rows()).filter(|&r| rs.visible[r] > 0).map(|r| sh.ext_id(r)).filter(|&x| x != u64::MAX).collect();
            live.sort_unstable();
            let seed: u64 = get(&m, "seed", 1);
            let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
            for i in (1..live.len()).rev() {
                let j = rng.random_range(0..=i);
                live.swap(i, j);
            }
            let n_del: usize = get(&m, "n-del", live.len() / 20);
            let n_upd: usize = get(&m, "n-upd", live.len() / 10);
            let n_ins: usize = get(&m, "n-ins", live.len() / 40);
            let id_off: u64 = get(&m, "id-off", 5_000_000 + 100_000 * seed);
            let (n_del, n_upd) = (n_del.min(live.len()), n_upd.min(live.len().saturating_sub(n_del)));
            let mut recs = Vec::new();
            for &id in &live[..n_del] {
                recs.push(Rec { op: OP_DELETE, id, comps: vec![], vals: vec![] });
            }
            for &id in &live[n_del..n_del + n_upd] {
                let (c, v) = random_vec(&mut rng, sh.dim, 4, 24);
                recs.push(Rec { op: OP_UPSERT, id, comps: c, vals: v });
            }
            for k in 0..n_ins {
                let (c, v) = random_vec(&mut rng, sh.dim, 4, 24);
                recs.push(Rec { op: OP_UPSERT, id: id_off + k as u64, comps: c, vals: v });
            }
            let out = PathBuf::from(req(&m, "out")?);
            write_batch(&out, &recs)?;
            Ok(serde_json::json!({"out": out, "live": live.len(), "deletes": n_del, "updates": n_upd, "inserts": n_ins, "epoch": e, "label": "SYNTHETIC"}))
        }
        "apply" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            let recs = read_batch(&PathBuf::from(req(&m, "batch")?))?;
            let mut sh = Shard::open(&dir)?;
            if let Some(p) = m.get("op-log") {
                sh.wlog.log = Some(BufWriter::with_capacity(1 << 22, File::create(p)?));
            }
            sh.wlog.crash_after = m.get("crash-after-op").and_then(|v| v.parse().ok());
            let (arm, tail_suffix) = Arm::parse_full(&req(&m, "arm")?)?;
            let opts = Opts {
                arm,
                tail: tail_suffix || m.contains_key("tail"),
                heap_reuse: get::<u32>(&m, "heap-reuse", 1) != 0,
                reader_timeout: Duration::from_secs(get(&m, "reader-timeout-s", 600)),
                hybrid_min_slots: get(&m, "hybrid-min-slots", 0),
                hold_between_flips: Duration::from_millis(get(&m, "hold-between-flips-ms", 0)),
                ..Default::default()
            };
            let table = Arc::new(Table::open(&dir.join("readers.bin"))?);
            let r = run_batch(&mut sh, &recs, &opts, table);
            sh.flush_log()?;
            let r = r?;
            let mut v = serde_json::to_value(&r)?;
            let io = std::fs::read_to_string("/proc/self/io").unwrap_or_default();
            let mut iom = serde_json::Map::new();
            for line in io.lines() {
                if let Some((k, x)) = line.split_once(':') {
                    iom.insert(k.trim().to_string(), serde_json::json!(x.trim().parse::<u64>().unwrap_or(0)));
                }
            }
            v["proc_self_io"] = serde_json::Value::Object(iom);
            if let Some(p) = m.get("report") {
                std::fs::write(p, serde_json::to_vec_pretty(&v)?)?;
            }
            Ok(v)
        }
        "recover" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            let mut sh = Shard::open(&dir)?;
            let table = Table::open(&dir.join("readers.bin"))?;
            Ok(serde_json::to_value(recover(&mut sh, Some(&table))?)?)
        }
        "verify" => {
            let sh = Shard::open(&PathBuf::from(req(&m, "dir")?))?;
            Ok(serde_json::to_value(verify(&sh, m.contains_key("deep"))?)?)
        }
        "search" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            let sh = Shard::open(&dir)?;
            let qs = load_queries(&req(&m, "queries")?)?;
            let k: usize = get(&m, "k", 200);
            let sleep = Duration::from_millis(get(&m, "sleep-ms", 0));
            if let Some(es) = m.get("epoch") {
                use rayon::prelude::*;
                let e: u64 = if es == "published" { sh.epoch() } else { es.parse().map_err(|_| Error::Msg("bad --epoch".into()))? };
                let hits: Vec<Result<serde_json::Value>> = qs
                    .par_iter()
                    .map(|(_, q)| Ok(serde_json::to_value(search_at(&sh, e, q, k, Duration::ZERO, None)?)?))
                    .collect();
                let mut res = serde_json::Map::new();
                for ((id, _), h) in qs.iter().zip(hits) {
                    res.insert(id.clone(), h?);
                }
                let out = serde_json::json!({"epoch": e, "slots": format!("{:?}", sh.slots()), "results": res});
                if let Some(p) = m.get("out") {
                    std::fs::write(p, serde_json::to_vec(&out)?)?;
                    return Ok(serde_json::json!({"out": p, "epoch": e}));
                }
                return Ok(out);
            }
            let table = Arc::new(Table::open(&dir.join("readers.bin"))?);
            let g = ReaderGuard::claim(table, get::<u64>(&m, "lease-ms", 0) * 1_000_000, !m.contains_key("no-heartbeat"))?;
            let loop_s: f64 = get(&m, "loop-s", 0.0);
            let t0 = Instant::now();
            let mut passes = Vec::new();
            loop {
                let mut res = serde_json::Map::new();
                let mut epochs = Vec::new();
                let mut errors = Vec::new();
                for (id, q) in &qs {
                    match search_registered(&sh, &g, q, k, sleep) {
                        Ok((e, hits)) => {
                            epochs.push(e);
                            res.insert(id.clone(), serde_json::json!({"epoch": e, "hits": hits}));
                        }
                        Err(x) => errors.push(format!("{id}: {x}")),
                    }
                }
                passes.push(serde_json::json!({"t": t0.elapsed().as_secs_f64(), "results": res, "errors": errors}));
                if t0.elapsed().as_secs_f64() >= loop_s {
                    break;
                }
            }
            let out = serde_json::json!({"passes": passes});
            if let Some(p) = m.get("out") {
                std::fs::write(p, serde_json::to_vec(&out)?)?;
                return Ok(serde_json::json!({"out": p, "passes": passes.len()}));
            }
            Ok(out)
        }
        "crash" => {
            let ops = load_ops(&PathBuf::from(req(&m, "log")?))?;
            let (img, touched) = materialize(&PathBuf::from(req(&m, "dir")?), &ops, get(&m, "cut", 0), req(&m, "model")? == "pages", get(&m, "seed", 0))?;
            Ok(serde_json::json!({"n_ops": ops.len(), "durable_writes": img.n_durable, "pages_kept": img.n_pages_kept,
                                  "pages_dropped": img.n_pages_dropped, "free_list_replaced": img.free_list_replaced(),
                                  "side_files_replaced": img.side_files.keys().collect::<Vec<_>>(), "ranges": touched.len()}))
        }
        "restore" => {
            let ops = load_ops(&PathBuf::from(req(&m, "log")?))?;
            let b = restore(&PathBuf::from(req(&m, "dir")?), &PathBuf::from(req(&m, "pristine")?), &ops)?;
            Ok(serde_json::json!({"restored_bytes": b}))
        }
        "sentinel" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            inplace_updater::guard::write_sentinel(&dir, &req(&m, "source-fnv")?)?;
            Ok(serde_json::json!({"sentinel": inplace_updater::guard::check_writable(&dir)?}))
        }
        "guard-check" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            Ok(serde_json::json!({"ok": inplace_updater::guard::check_writable(&dir)?}))
        }
        "nops" => {
            let ops = load_ops(&PathBuf::from(req(&m, "log")?))?;
            let logical: usize = ops.iter().map(|o| o.data.len()).sum();
            Ok(serde_json::json!({"n_ops": ops.len(), "logical_bytes": logical}))
        }
        "identity" => {
            let sh = Shard::open(&PathBuf::from(req(&m, "dir")?))?;
            Ok(identity(sh.pl(), &sh.lists, get(&m, "lists", usize::MAX)))
        }
        "identity-v2" => {
            let dir = PathBuf::from(req(&m, "dir")?);
            let man: serde_json::Value = serde_json::from_slice(&std::fs::read(dir.join("manifest.json"))?)?;
            let lists: Vec<ListManifest> = serde_json::from_value(man["posting_lists"].clone())?;
            let f = File::open(dir.join("posting_lists.bin"))?;
            let map = unsafe { memmap2::Mmap::map(&f)? };
            Ok(identity(&map, &lists, get(&m, "lists", usize::MAX)))
        }
        _ => Err(Error::Msg(format!("unknown command {cmd:?}"))),
    }
}

fn main() {
    match run() {
        Ok(v) => println!("{}", serde_json::to_string(&v).unwrap()),
        Err(e) => {
            println!("{}", serde_json::json!({"error": e.to_string(), "injected": matches!(e, Error::Injected(_))}));
            std::process::exit(match e {
                Error::Injected(_) => 3,
                _ => 1,
            });
        }
    }
}
