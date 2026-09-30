//! Synthetic v3 shard builder (tests; SYNTHETIC runs). Built from
//! FORMAT_V3.md + the dv-v2 layout only: vectorium dv-v2 records, top-cap
//! truncated lists, fixed-size blocks, energy-preserving summaries encoded by
//! `summary::encode_list`, side files as `convert_dv_v2_to_inplace_v3` writes
//! them. Independent of the encoder agent's converter.

use std::collections::HashMap;
use std::fs::File;
use std::io::Write;
use std::path::Path;

use rand::{Rng, SeedableRng};
use rand_chacha::ChaCha8Rng;
use vectorium::DotVByteFixedU8Encoder;

use crate::freelist::FreeList;
use crate::layout::{walk, ListManifest};
use crate::readers::{N_SLOTS, SLOT};
use crate::store::{decode_with, encode_with, header_record, HEADER_BYTES, FREE_BIT};
use crate::summary::{encode_list, energy_summary, raw_from_values};
use crate::util::{fnv1a64, Result};

#[derive(Debug, Clone)]
pub struct SynthParams {
    pub n_docs: usize,
    pub dim: usize,
    pub cap: usize,
    pub block: usize,
    pub nnz_min: usize,
    pub nnz_max: usize,
    pub seed: u64,
    pub heap_factor: u64,
    pub id_base: u64,
    /// Forward tail reserve (v3.1, FORMAT_V3 rev. 6): 0/0 = the v3.0 layout
    /// (the `forward_tail` key is still written with zero reserves).
    pub tail_words: u64,
    pub tail_rows: u64,
}

impl Default for SynthParams {
    fn default() -> Self {
        SynthParams { n_docs: 2000, dim: 300, cap: 60, block: 8, nnz_min: 4, nnz_max: 24, seed: 7, heap_factor: 6, id_base: 1_000_000, tail_words: 0, tail_rows: 0 }
    }
}

/// A random sparse vector (components ascending, values in (0.05, 3)).
pub fn random_vec(rng: &mut ChaCha8Rng, dim: usize, nnz_min: usize, nnz_max: usize) -> (Vec<u16>, Vec<f32>) {
    let n = rng.random_range(nnz_min..=nnz_max);
    let mut cs: Vec<u16> = Vec::with_capacity(n);
    while cs.len() < n {
        let u: f64 = rng.random();
        let c = ((u * u) * dim as f64) as usize;
        let c = c.min(dim - 1) as u16;
        if !cs.contains(&c) {
            cs.push(c);
        }
    }
    cs.sort_unstable();
    let vs = cs.iter().map(|_| 0.05 + rng.random::<f32>() * 2.95).collect();
    (cs, vs)
}

fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut f = File::create(path)?;
    f.write_all(bytes)?;
    f.sync_all()?;
    Ok(())
}

/// Build a v3 dir at `dst` (must not exist). Returns the base vectors
/// (row order) for model checks.
pub fn build(dst: &Path, p: &SynthParams) -> Result<Vec<(u64, Vec<u16>, Vec<f32>)>> {
    let dst_c = crate::guard::check_new_dir(dst)?;
    let dst: &Path = &dst_c;
    std::fs::create_dir_all(dst)?;
    let mut rng = ChaCha8Rng::seed_from_u64(p.seed);
    let mut enc = DotVByteFixedU8Encoder::new(p.dim, p.dim);
    enc.set_per_doc_scale(true);
    let mut data: Vec<u64> = Vec::new();
    let mut offs: Vec<u64> = vec![0];
    let mut dec: Vec<(Vec<u16>, Vec<f32>)> = Vec::with_capacity(p.n_docs);
    let mut base = Vec::with_capacity(p.n_docs);
    let mut nnz_total = 0usize;
    for r in 0..p.n_docs {
        let (c, v) = random_vec(&mut rng, p.dim, p.nnz_min, p.nnz_max);
        let rec = encode_with(&enc, &c, &v);
        data.extend_from_slice(&rec);
        offs.push(data.len() as u64);
        let d = decode_with(&enc, &rec);
        nnz_total += d.0.len();
        let id = p.id_base + 7 * r as u64;
        base.push((id, c, v));
        dec.push(d);
    }
    let mut per_list: Vec<Vec<(f32, usize)>> = vec![Vec::new(); p.dim];
    for (r, (c, v)) in dec.iter().enumerate() {
        for (&ci, &vi) in c.iter().zip(v) {
            if vi > 0.0 {
                per_list[ci as usize].push((vi, r));
            }
        }
    }
    let mut pl_buf: Vec<u8> = Vec::new();
    let mut mans: Vec<ListManifest> = Vec::with_capacity(p.dim);
    let mut list_min: Vec<u64> = Vec::with_capacity(p.dim);
    let mut n_blocks_total = 0usize;
    for t in 0..p.dim {
        let mut ps = per_list[t].clone();
        ps.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
        ps.truncate(p.cap);
        ps.sort_by_key(|x| x.1);
        let mut words = Vec::with_capacity(ps.len());
        let mut bo = Vec::new();
        let mut blocks = Vec::new();
        if !ps.is_empty() {
            bo.push(0);
            for chunk in ps.chunks(p.block) {
                let refs: Vec<(&[u16], &[f32])> = chunk.iter().map(|&(_, r)| (dec[r].0.as_slice(), dec[r].1.as_slice())).collect();
                let (sc, sv) = energy_summary(&refs, 0.4);
                blocks.push(raw_from_values(sc, &sv));
                for &(_, r) in chunk {
                    words.push((offs[r] << 16) | (offs[r + 1] - offs[r]));
                }
                bo.push(words.len());
            }
        }
        n_blocks_total += blocks.len();
        let mut best: Option<(f32, usize)> = None;
        for (i, &(_, r)) in ps.iter().enumerate() {
            let w = per_list[t].iter().find(|x| x.1 == r).unwrap().0;
            if best.map_or(true, |(b, _)| w < b) {
                best = Some((w, i));
            }
        }
        list_min.push(match best {
            None => FREE_BIT,
            Some((w, i)) => (w.to_bits() as u64) | ((i as u64) << 32),
        });
        let (body, man) = encode_list(&words, &bo, &blocks, p.dim);
        while pl_buf.len() % 8 != 0 {
            pl_buf.push(0);
        }
        pl_buf.extend_from_slice(&body);
        mans.push(man);
    }
    let locs = walk(&mans);
    assert_eq!(locs.last().map(|l| l.end).unwrap_or(0), pl_buf.len());
    write(&dst.join("posting_lists.bin"), &pl_buf)?;
    write(&dst.join("forward_data.bin"), bytemuck::cast_slice(&data))?;
    write(&dst.join("forward_offsets.bin"), bytemuck::cast_slice(&offs))?;
    let base_words = data.len() as u64;
    if p.tail_words > 0 || p.tail_rows > 0 {
        let extend = |name: &str, bytes: u64| -> Result<()> {
            let f = std::fs::OpenOptions::new().write(true).open(dst.join(name))?;
            f.set_len(bytes)?;
            f.sync_all()?;
            Ok(())
        };
        extend("forward_data.bin", 8 * (base_words + p.tail_words))?;
        extend("forward_offsets.bin", 8 * (p.n_docs as u64 + 1 + p.tail_rows))?;
    }
    let cfgb = bincode::config::standard().with_fixed_int_encoding().with_little_endian();
    write(&dst.join("forward_encoder.bin"), &bincode::serde::encode_to_vec(&enc, cfgb).unwrap())?;
    let tok: HashMap<String, usize> = (0..p.dim).map(|i| (format!("t{i}"), i)).collect();
    write(&dst.join("token_to_id_map.bin"), &bincode::serde::encode_to_vec(&tok, cfgb).unwrap())?;
    let mut strings = Vec::new();
    let mut soffs: Vec<u64> = vec![0];
    for (id, _, _) in &base {
        strings.extend_from_slice(format!("W{id}").as_bytes());
        soffs.push(strings.len() as u64);
    }
    write(&dst.join("document_mapping_strings.bin"), &strings)?;
    write(&dst.join("document_mapping_offsets.bin"), bytemuck::cast_slice(&soffs))?;
    let config = r#"{"pruning":{"GlobalThreshold":{"n_postings":0,"max_fraction":0}},"blocking":{"FixedSize":{"block_size":8}},"summarization":{"EnergyPreserving":{"summary_energy":0.4}},"knn":{"nknn":0,"knn_path":null}}"#;
    write(&dst.join("config.json"), config.as_bytes())?;
    let native: Vec<u64> = locs.iter().map(|l| l.pp as u64).collect();
    let mut dirb = native.clone();
    dirb.extend_from_slice(&native);
    write(&dst.join("list_dir.bin"), bytemuck::cast_slice(&dirb))?;
    let crc: Vec<u64> = locs.iter().map(|l| fnv1a64(&pl_buf[l.pp..l.end])).collect();
    write(&dst.join("list_crc.bin"), bytemuck::cast_slice(&crc))?;
    let reserve = ((pl_buf.len() as u64 * p.heap_factor) + 4095) / 4096 * 4096;
    File::create(dst.join("posting_heap.bin"))?.set_len(reserve)?;
    let mut pfree = vec![0u8; 64];
    pfree[0..8].copy_from_slice(&u64::from_le_bytes(*b"SFUPFL3\0").to_le_bytes());
    pfree[8..12].copy_from_slice(&3u32.to_le_bytes());
    let ck = fnv1a64(&pfree[0..56]);
    pfree[56..64].copy_from_slice(&ck.to_le_bytes());
    write(&dst.join("posting_free.bin"), &pfree)?;
    write(&dst.join("block_inflation.bin"), &vec![0u8; 2 * n_blocks_total])?;
    write(&dst.join("list_min.bin"), bytemuck::cast_slice(&list_min))?;
    write(&dst.join("forward_free.bin"), &FreeList::default().serialize())?;
    File::create(dst.join("row_id_override.bin"))?.set_len(8 * (p.n_docs as u64 + p.tail_rows))?;
    File::create(dst.join("readers.bin"))?.set_len((N_SLOTS * SLOT) as u64)?;
    let man = serde_json::json!({
        "n_posting_lists": p.dim,
        "forward_offsets_len": p.n_docs + 1,
        "forward_components_len": 0,
        "forward_values_len": 0,
        "n_docs": p.n_docs,
        "has_knn": false,
        "config_json": config,
        "forward_format": "dotvbyte_fixedu8",
        "forward_data_words": data.len(),
        "forward_nnz": nnz_total,
        "forward_page_aligned": false,
        "forward_reordered": "none",
        "forward_format_version": 3,
        "posting_lists": mans,
        "inplace_v3": {
            "format": "sfu_inplace_v3", "version": 3, "record_envelope_version": 2,
            "n_blocks_total": n_blocks_total,
            "minor": if p.tail_words > 0 || p.tail_rows > 0 { 1 } else { 0 },
            "a2b_reserved": {"posting_heap": {"file": "posting_heap.bin", "reserve_bytes": reserve, "base": pl_buf.len()}},
            "forward_tail": {"base_words": base_words, "reserve_words": p.tail_words, "reserve_rows": p.tail_rows,
                             "offsets_entries_on_disk": p.n_docs as u64 + 1 + p.tail_rows,
                             "override_entries_on_disk": p.n_docs as u64 + p.tail_rows,
                             "tail_words_used_field": 64, "tail_rows_published_field": 72},
            "source": {"dir": "SYNTHETIC", "seed": p.seed},
        }
    });
    let man_bytes = serde_json::to_vec_pretty(&man)?;
    write(&dst.join("manifest.json"), &man_bytes)?;
    let mut hdr = vec![0u8; HEADER_BYTES];
    hdr[0..128].copy_from_slice(&header_record(0, 0, p.n_docs as u64, p.dim as u64, n_blocks_total as u64, fnv1a64(&man_bytes), 0, 0, 0));
    write(&dst.join("inplace_header.bin"), &hdr)?;
    crate::guard::write_sentinel(dst, &format!("{:016x}", fnv1a64(&man_bytes)))?;
    File::open(dst)?.sync_all()?;
    Ok(base)
}
