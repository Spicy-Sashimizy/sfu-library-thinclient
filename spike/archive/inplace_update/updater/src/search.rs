//! Reference search: exact list-restricted retrieval over the postings
//! visible at the published epoch (candidates = union of the query terms'
//! active lists; score = f32 dot of the query with the decoded record,
//! accumulated in query-component order; ties by external id). Used by the
//! tests and by B7 on synthetic shards and for A2b (the v3 decoder cannot read
//! A2b units yet). Not the engine's approximate traversal.

use std::collections::HashSet;
use std::time::Duration;

use crate::readers::ReaderGuard;
use crate::store::{visible, w_len, w_start, Shard};
use crate::util::Result;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Hit {
    pub id: u64,
    pub score_bits: u32,
}

pub struct Query {
    pub comps: Vec<u16>,
    pub vals: Vec<f32>,
}

/// Search at a fixed epoch e (caller registered it). `per_list_sleep` makes
/// a deliberately slow reader; `guard` (if any) is checked per list, as the
/// decoder refreshes/validates per query term.
pub fn search_at(sh: &Shard, e: u64, q: &Query, k: usize, per_list_sleep: Duration, guard: Option<&ReaderGuard>) -> Result<Vec<Hit>> {
    let bank = (e & 1) as usize;
    let mut cands: HashSet<(usize, usize)> = HashSet::new();
    for &t in &q.comps {
        if (t as usize) >= sh.n_lists {
            continue;
        }
        if let Some(g) = guard {
            g.check()?;
        }
        let v = sh.view(t as usize, bank, false)?;
        for &w in &v.words {
            if visible(w, e) {
                cands.insert((w_start(w), w_len(w)));
            }
        }
        if !per_list_sleep.is_zero() {
            std::thread::sleep(per_list_sleep);
        }
    }
    let mut hits: Vec<(f32, u64)> = Vec::with_capacity(cands.len());
    for (s, l) in cands {
        let (c, v) = sh.decode(s, l);
        let mut acc = 0f32;
        for (qc, qv) in q.comps.iter().zip(&q.vals) {
            if let Ok(i) = c.binary_search(qc) {
                acc += qv * v[i];
            }
        }
        let row = sh.row_of_start(s).unwrap_or(usize::MAX);
        let id = if row == usize::MAX { u64::MAX } else { sh.ext_id(row) };
        hits.push((acc, id));
    }
    hits.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
    hits.truncate(k);
    Ok(hits.into_iter().map(|(s, id)| Hit { id, score_bits: s.to_bits() }).collect())
}

/// Register (with re-read), search at the registered epoch, end (fails if
/// the slot was reclaimed during the query).
pub fn search_registered(sh: &Shard, g: &ReaderGuard, q: &Query, k: usize, per_list_sleep: Duration) -> Result<(u64, Vec<Hit>)> {
    let e = g.begin(|| sh.epoch())?;
    let r = search_at(sh, e, q, k, per_list_sleep, Some(g));
    let end = g.end();
    let hits = r?;
    end?;
    Ok((e, hits))
}
