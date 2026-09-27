//! N2 — MPHF viability for ordinal addressing (doc 18 §7 N2).
//!
//! Subcommands (all paths are local scratch, never data/):
//!   build   <wids.npy> <outdir>            build PtrHash over the W-ids, store mphf.bin (epserde)
//!   payload <wids.npy> <outdir>            slot for every key -> keys_by_slot.u64, perm.u32, fp8.u8, fp16.u16
//!   genq    <wids.npy> <outdir> <n> <seed> n random member ids + n random NON-member ids in [min,max]
//!   bench   <wids.npy> <outdir> <arm>      one arm, cold + warm, hits + misses; prints one JSON object
//!
//! Arms:
//!   bsearch         binary search over the sorted 1.2 GB wids.npy (the current baseline; ordinal = position)
//!   mphf_only       PtrHash index only, NO verification (reference only: cannot reject non-members)
//!   mphf_keys       PtrHash slot + read keys_by_slot[slot] == key (exact; ordinal := slot, i.e. renumbered)
//!   mphf_perm_wids  PtrHash slot -> perm[slot] (existing ordinal) -> wids[ord] == key (exact; keeps numbering)
//!   mphf_fp8/16     PtrHash slot + 8/16-bit fingerprint at slot (probabilistic; false accepts reported)

use epserde::prelude::*;
use ptr_hash::{bucket_fn::Linear, hash::Xxh3Int, PtrHash, PtrHashParams};
use std::fs::File;
use std::hint::black_box;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Instant;

// Xxh3Int: strong integer hash (W-ids are structured, sorted integers; FxHash is the
// crate default but is not epserde-serialisable and is weaker on structured keys).
type Mphf = PtrHash<u64, Linear, Vec<u32>, Xxh3Int, Vec<u8>>;

const FP_SEED: u64 = 0x5f1d_2026_0927_00f5;

fn fp64(key: u64) -> u64 {
    xxhash_rust::xxh3::xxh3_64_with_seed(&key.to_le_bytes(), FP_SEED)
}

// ---------------------------------------------------------------- npy / mmap helpers

struct U64Map {
    _mmap: memmap2::Mmap,
    ptr: *const u64,
    len: usize,
}
impl U64Map {
    fn slice(&self) -> &[u64] {
        unsafe { std::slice::from_raw_parts(self.ptr, self.len) }
    }
}

/// mmap an .npy of little-endian int64/uint64 (header parsed, data zero-copy).
fn map_npy_u64(path: &Path) -> U64Map {
    let f = File::open(path).unwrap();
    let m = unsafe { memmap2::MmapOptions::new().map(&f).unwrap() };
    assert_eq!(&m[..6], b"\x93NUMPY");
    let (hlen, hstart) = if m[6] == 1 {
        (u16::from_le_bytes([m[8], m[9]]) as usize, 10)
    } else {
        (u32::from_le_bytes([m[8], m[9], m[10], m[11]]) as usize, 12)
    };
    let header = std::str::from_utf8(&m[hstart..hstart + hlen]).unwrap();
    assert!(header.contains("'<i8'") || header.contains("'<u8'"), "dtype: {header}");
    assert!(header.contains("'fortran_order': False"));
    let off = hstart + hlen;
    let len = (m.len() - off) / 8;
    assert_eq!(off % 8, 0, "npy data not 8-byte aligned");
    let ptr = unsafe { m.as_ptr().add(off) as *const u64 };
    let _ = m.advise(memmap2::Advice::Random);
    U64Map { _mmap: m, ptr, len }
}

struct RawMap {
    m: memmap2::Mmap,
}
impl RawMap {
    fn open(path: &Path) -> RawMap {
        let f = File::open(path).unwrap();
        let m = unsafe { memmap2::MmapOptions::new().map(&f).unwrap() };
        let _ = m.advise(memmap2::Advice::Random);
        RawMap { m }
    }
    fn as_slice<T>(&self) -> &[T] {
        let sz = std::mem::size_of::<T>();
        assert_eq!(self.m.as_ptr() as usize % std::mem::align_of::<T>(), 0);
        unsafe { std::slice::from_raw_parts(self.m.as_ptr() as *const T, self.m.len() / sz) }
    }
}

fn write_slice<T: Copy>(path: &Path, v: &[T]) {
    let bytes = unsafe {
        std::slice::from_raw_parts(v.as_ptr() as *const u8, v.len() * std::mem::size_of::<T>())
    };
    let mut f = std::io::BufWriter::with_capacity(1 << 24, File::create(path).unwrap());
    f.write_all(bytes).unwrap();
    f.flush().unwrap();
}

fn read_u64_file(path: &Path) -> Vec<u64> {
    let b = std::fs::read(path).unwrap();
    b.chunks_exact(8).map(|c| u64::from_le_bytes(c.try_into().unwrap())).collect()
}

/// Drop a file's clean pages from the page cache (no root needed). Must be called
/// while no mapping of the file is alive in this process.
fn evict(path: &Path) {
    let f = File::open(path).unwrap();
    use std::os::fd::AsRawFd;
    unsafe {
        libc::fsync(f.as_raw_fd());
        libc::posix_fadvise(f.as_raw_fd(), 0, 0, libc::POSIX_FADV_DONTNEED);
    }
}

/// Bytes of `path` currently in the page cache (mincore over a fresh mapping).
fn resident_bytes(path: &Path) -> (u64, u64) {
    let f = File::open(path).unwrap();
    let len = f.metadata().unwrap().len() as usize;
    if len == 0 {
        return (0, 0);
    }
    let m = unsafe { memmap2::MmapOptions::new().map(&f).unwrap() };
    let page = 4096usize;
    let pages = len.div_ceil(page);
    let mut vec = vec![0u8; pages];
    unsafe {
        libc::mincore(m.as_ptr() as *mut libc::c_void, len, vec.as_mut_ptr());
    }
    let res = vec.iter().filter(|&&b| b & 1 == 1).count() as u64;
    (res * page as u64, len as u64)
}

fn proc_status_kb(field: &str) -> u64 {
    let s = std::fs::read_to_string("/proc/self/status").unwrap();
    for line in s.lines() {
        if let Some(rest) = line.strip_prefix(field) {
            return rest.trim_start_matches(':').trim().trim_end_matches("kB").trim().parse().unwrap_or(0);
        }
    }
    0
}

fn maxrss_kb() -> u64 {
    let mut ru: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut ru) };
    ru.ru_maxrss as u64
}

// ---------------------------------------------------------------- timing

#[inline(always)]
fn tsc() -> u64 {
    let mut aux = 0u32;
    unsafe { core::arch::x86_64::__rdtscp(&mut aux) }
}

fn tsc_ghz() -> f64 {
    let t0 = Instant::now();
    let c0 = tsc();
    while t0.elapsed().as_millis() < 300 {}
    let c1 = tsc();
    (c1 - c0) as f64 / t0.elapsed().as_nanos() as f64
}

fn timer_overhead_cycles() -> u64 {
    let mut v: Vec<u64> = (0..200_000)
        .map(|_| {
            let a = tsc();
            let b = tsc();
            b - a
        })
        .collect();
    v.sort_unstable();
    v[v.len() / 2]
}

// ---------------------------------------------------------------- build

fn cmd_build(wids: &Path, out: &Path) {
    std::fs::create_dir_all(out).unwrap();
    let t_load = Instant::now();
    let map = map_npy_u64(wids);
    let keys = map.slice();
    let mut s = 0u64;
    for &k in keys {
        s = s.wrapping_add(k);
    }
    black_box(s);
    let load_s = t_load.elapsed().as_secs_f64();
    let rss_before = maxrss_kb();
    let t = Instant::now();
    let mphf = Mphf::new(keys, PtrHashParams::default());
    let build_s = t.elapsed().as_secs_f64();
    let rss_after = maxrss_kb();
    let path = out.join("mphf.bin");
    let t2 = Instant::now();
    unsafe { mphf.store(&path).unwrap() };
    let store_s = t2.elapsed().as_secs_f64();
    let size = std::fs::metadata(&path).unwrap().len();
    let (pilot_bits, remap_bits) = mphf.bits_per_element();
    println!(
        "{{\"n\":{},\"params\":\"PtrHashParams::default() (Linear bucket fn, single part, remap Vec<u32>, Xxh3Int)\",\
\"key_load_touch_s\":{:.3},\"construction_s\":{:.3},\"store_s\":{:.3},\"mphf_bytes\":{},\
\"bits_per_key_file\":{:.4},\"pilot_bits_per_key\":{:.4},\"remap_bits_per_key\":{:.4},\
\"maxrss_kb_before_build\":{},\"maxrss_kb_after_build\":{},\"threads\":{}}}",
        keys.len(),
        load_s,
        build_s,
        store_s,
        size,
        size as f64 * 8.0 / keys.len() as f64,
        pilot_bits,
        remap_bits,
        rss_before,
        rss_after,
        rayon::current_num_threads()
    );
}

fn load_mphf(out: &Path) -> MemCase<Mphf> {
    unsafe { Mphf::mmap(out.join("mphf.bin"), Flags::RANDOM_ACCESS).unwrap() }
}

fn cmd_payload(wids: &Path, out: &Path) {
    let map = map_npy_u64(wids);
    let keys = map.slice();
    let n = keys.len();
    let case = load_mphf(out);
    let mphf = case.uncase();
    let t = Instant::now();
    let mut keys_by_slot = vec![u64::MAX; n];
    let mut perm = vec![u32::MAX; n];
    let mut fp8 = vec![0u8; n];
    let mut fp16 = vec![0u16; n];
    let mut dup = 0u64;
    for (ord, &k) in keys.iter().enumerate() {
        let s = mphf.index(&k);
        assert!(s < n);
        if keys_by_slot[s] != u64::MAX {
            dup += 1;
        }
        keys_by_slot[s] = k;
        perm[s] = ord as u32;
        let h = fp64(k);
        fp8[s] = (h >> 56) as u8;
        fp16[s] = (h >> 48) as u16;
    }
    let slot_s = t.elapsed().as_secs_f64();
    let empty = keys_by_slot.iter().filter(|&&k| k == u64::MAX).count();
    assert!(n <= u32::MAX as usize);
    write_slice(&out.join("keys_by_slot.u64"), &keys_by_slot);
    write_slice(&out.join("perm.u32"), &perm);
    write_slice(&out.join("fp8.u8"), &fp8);
    write_slice(&out.join("fp16.u16"), &fp16);
    let total_s = t.elapsed().as_secs_f64();
    println!(
        "{{\"n\":{n},\"slot_collisions\":{dup},\"empty_slots\":{empty},\"minimal_perfect\":{},\
\"slot_pass_s\":{slot_s:.3},\"payload_total_s\":{total_s:.3},\"maxrss_kb\":{}}}",
        dup == 0 && empty == 0,
        maxrss_kb()
    );
}

// ---------------------------------------------------------------- queries

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
}

fn cmd_genq(wids: &Path, out: &Path, n: usize, seed: u64) {
    let map = map_npy_u64(wids);
    let keys = map.slice();
    let (lo, hi) = (keys[0], keys[keys.len() - 1]);
    let mut r = Rng(seed | 1);
    let hits: Vec<u64> = (0..n).map(|_| keys[(r.next() % keys.len() as u64) as usize]).collect();
    let mut misses = Vec::with_capacity(n);
    let mut rejected = 0u64;
    while misses.len() < n {
        let c = lo + r.next() % (hi - lo + 1);
        if keys.binary_search(&c).is_ok() {
            rejected += 1;
            continue;
        }
        misses.push(c);
    }
    write_slice(&out.join("q_hit.u64"), &hits);
    write_slice(&out.join("q_miss.u64"), &misses);
    println!(
        "{{\"n\":{n},\"seed\":{seed},\"key_min\":{lo},\"key_max\":{hi},\"miss_candidates_rejected_as_members\":{rejected},\
\"key_density\":{:.6}}}",
        keys.len() as f64 / (hi - lo + 1) as f64
    );
}

// ---------------------------------------------------------------- bench

/// Result of one lookup: Some(ordinal/slot) if accepted as a member, None if rejected.
struct Arm<'a> {
    name: &'a str,
    wids: Option<&'a [u64]>,
    mphf: Option<&'a DeserType<'a, Mphf>>,
    keys_by_slot: Option<&'a [u64]>,
    perm: Option<&'a [u32]>,
    fp8: Option<&'a [u8]>,
    fp16: Option<&'a [u16]>,
}

impl Arm<'_> {
    #[inline(always)]
    fn lookup(&self, k: u64) -> Option<usize> {
        match self.name {
            "bsearch" => self.wids.unwrap().binary_search(&k).ok(),
            "mphf_only" => Some(self.mphf.unwrap().index(&k)),
            "mphf_keys" => {
                let s = self.mphf.unwrap().index(&k);
                if unsafe { *self.keys_by_slot.unwrap().get_unchecked(s) } == k { Some(s) } else { None }
            }
            "mphf_perm_wids" => {
                let s = self.mphf.unwrap().index(&k);
                let o = unsafe { *self.perm.unwrap().get_unchecked(s) } as usize;
                if unsafe { *self.wids.unwrap().get_unchecked(o) } == k { Some(o) } else { None }
            }
            "mphf_fp8" => {
                let s = self.mphf.unwrap().index(&k);
                if unsafe { *self.fp8.unwrap().get_unchecked(s) } == (fp64(k) >> 56) as u8 { Some(s) } else { None }
            }
            "mphf_fp16" => {
                let s = self.mphf.unwrap().index(&k);
                if unsafe { *self.fp16.unwrap().get_unchecked(s) } == (fp64(k) >> 48) as u16 { Some(s) } else { None }
            }
            _ => unreachable!(),
        }
    }
}

fn arm_files(arm: &str, wids: &Path, out: &Path) -> Vec<PathBuf> {
    let mut v = vec![];
    if arm != "bsearch" {
        v.push(out.join("mphf.bin"));
    }
    match arm {
        "bsearch" => v.push(wids.to_path_buf()),
        "mphf_keys" => v.push(out.join("keys_by_slot.u64")),
        "mphf_perm_wids" => {
            v.push(out.join("perm.u32"));
            v.push(wids.to_path_buf());
        }
        "mphf_fp8" => v.push(out.join("fp8.u8")),
        "mphf_fp16" => v.push(out.join("fp16.u16")),
        _ => {}
    }
    v
}

struct PassStats {
    json: String,
    accepted: usize,
}

fn pct(sorted: &[u64], p: f64) -> u64 {
    sorted[((sorted.len() as f64 - 1.0) * p).round() as usize]
}

/// Per-key timed pass (rdtscp around each lookup, timer overhead subtracted),
/// followed (warm only) by an untimed-per-key throughput loop.
fn run_pass(arm: &Arm, q: &[u64], ghz: f64, ovh: u64, throughput: bool) -> PassStats {
    let mut cyc = Vec::with_capacity(q.len());
    let mut accepted = 0usize;
    let t = Instant::now();
    for &k in q {
        let a = tsc();
        let r = black_box(arm.lookup(black_box(k)));
        let b = tsc();
        cyc.push((b - a).saturating_sub(ovh));
        accepted += r.is_some() as usize;
    }
    let wall_ns = t.elapsed().as_nanos() as f64 / q.len() as f64;
    let mean_ns = cyc.iter().sum::<u64>() as f64 / cyc.len() as f64 / ghz;
    cyc.sort_unstable();
    let ns = |c: u64| c as f64 / ghz;
    let mut thr = String::from("null");
    if throughput {
        let t = Instant::now();
        let mut acc = 0usize;
        for &k in q {
            acc = acc.wrapping_add(arm.lookup(k).map_or(1, |o| o.wrapping_add(2)));
        }
        black_box(acc);
        thr = format!("{:.2}", t.elapsed().as_nanos() as f64 / q.len() as f64);
    }
    PassStats {
        json: format!(
            "{{\"n\":{},\"p50_ns\":{:.1},\"p90_ns\":{:.1},\"p99_ns\":{:.1},\"p999_ns\":{:.1},\"max_ns\":{:.1},\
\"mean_ns\":{:.2},\"wall_ns_per_key_incl_timer\":{:.2},\"throughput_loop_ns_per_key\":{},\"accepted\":{}}}",
            q.len(),
            ns(pct(&cyc, 0.5)),
            ns(pct(&cyc, 0.9)),
            ns(pct(&cyc, 0.99)),
            ns(pct(&cyc, 0.999)),
            ns(*cyc.last().unwrap()),
            mean_ns,
            wall_ns,
            thr,
            accepted
        ),
        accepted,
    }
}

/// Opens all mappings for `arm_name` and calls `f` with the arm.
fn with_arm<R>(arm_name: &str, wids: &Path, out: &Path, f: impl FnOnce(&Arm) -> R) -> R {
    let need = |s: &str| arm_files(arm_name, wids, out).iter().any(|p| p.to_string_lossy().ends_with(s));
    let wmap = if need("wids.npy") { Some(map_npy_u64(wids)) } else { None };
    let case = if arm_name != "bsearch" { Some(load_mphf(out)) } else { None };
    let kmap = if need("keys_by_slot.u64") { Some(RawMap::open(&out.join("keys_by_slot.u64"))) } else { None };
    let pmap = if need("perm.u32") { Some(RawMap::open(&out.join("perm.u32"))) } else { None };
    let f8 = if need("fp8.u8") { Some(RawMap::open(&out.join("fp8.u8"))) } else { None };
    let f16 = if need("fp16.u16") { Some(RawMap::open(&out.join("fp16.u16"))) } else { None };
    let arm = Arm {
        name: arm_name,
        wids: wmap.as_ref().map(|m| m.slice()),
        mphf: case.as_ref().map(|c| c.uncase()),
        keys_by_slot: kmap.as_ref().map(|m| m.as_slice::<u64>()),
        perm: pmap.as_ref().map(|m| m.as_slice::<u32>()),
        fp8: f8.as_ref().map(|m| m.as_slice::<u8>()),
        fp16: f16.as_ref().map(|m| m.as_slice::<u16>()),
    };
    f(&arm)
}

fn resident_json(files: &[PathBuf]) -> String {
    let mut parts = vec![];
    let mut tot = 0u64;
    let mut totsz = 0u64;
    for p in files {
        let (r, s) = resident_bytes(p);
        tot += r;
        totsz += s;
        parts.push(format!(
            "\"{}\":{{\"resident_bytes\":{r},\"file_bytes\":{s}}}",
            p.file_name().unwrap().to_string_lossy()
        ));
    }
    format!("{{{},\"total_resident_bytes\":{tot},\"total_file_bytes\":{totsz}}}", parts.join(","))
}

fn cmd_bench(wids: &Path, out: &Path, arm_name: &str) {
    let hits = read_u64_file(&out.join("q_hit.u64"));
    let misses = read_u64_file(&out.join("q_miss.u64"));
    let files = arm_files(arm_name, wids, out);
    let ghz = tsc_ghz();
    let ovh = timer_overhead_cycles();

    let mut cold = vec![];
    let mut resid_after_evict = vec![];
    for (label, q) in [("hits", &hits), ("misses", &misses)] {
        for p in &files {
            evict(p);
        }
        resid_after_evict.push(format!("\"{label}\":{}", resident_json(&files)));
        let t_open = Instant::now();
        let s = with_arm(arm_name, wids, out, |arm| {
            let open_ns = t_open.elapsed().as_nanos();
            let st = run_pass(arm, q, ghz, ovh, false);
            (st, open_ns)
        });
        cold.push(format!("\"{label}\":{{\"open_ns\":{},\"pass\":{}}}", s.1, s.0.json));
    }

    let (warm, correctness, rss) = with_arm(arm_name, wids, out, |arm| {
        let mut bad_hits = 0usize;
        for &k in hits.iter() {
            match arm.lookup(k) {
                None => bad_hits += 1,
                Some(o) => {
                    let ok = match arm.name {
                        "bsearch" | "mphf_perm_wids" => arm.wids.unwrap()[o] == k,
                        "mphf_only" => true,
                        "mphf_keys" => arm.keys_by_slot.unwrap()[o] == k,
                        _ => o < 150_413_098,
                    };
                    if !ok {
                        bad_hits += 1;
                    }
                }
            }
        }
        for &k in &misses {
            black_box(arm.lookup(k));
        }
        let wh = run_pass(arm, &hits, ghz, ovh, true);
        let wm = run_pass(arm, &misses, ghz, ovh, true);
        let rss = format!(
            "{{\"VmRSS_kb\":{},\"RssFile_kb\":{},\"RssAnon_kb\":{},\"page_cache\":{}}}",
            proc_status_kb("VmRSS"),
            proc_status_kb("RssFile"),
            proc_status_kb("RssAnon"),
            resident_json(&files)
        );
        let corr = format!(
            "{{\"hits_not_found_or_wrong\":{bad_hits},\"misses_false_accepts_warm\":{},\"miss_false_accept_rate\":{:.6}}}",
            wm.accepted,
            wm.accepted as f64 / misses.len() as f64
        );
        (format!("{{\"hits\":{},\"misses\":{}}}", wh.json, wm.json), corr, rss)
    });

    let sizes: u64 = files.iter().map(|p| std::fs::metadata(p).unwrap().len()).sum();
    println!(
        "{{\"arm\":\"{arm_name}\",\"files\":[{}],\"on_disk_bytes\":{sizes},\"tsc_ghz\":{ghz:.4},\"timer_overhead_cycles\":{ovh},\
\"resident_after_evict\":{{{}}},\"cold\":{{{}}},\"warm\":{warm},\"correctness\":{correctness},\"warm_resident\":{rss}}}",
        files.iter().map(|p| format!("\"{}\"", p.display())).collect::<Vec<_>>().join(","),
        resid_after_evict.join(","),
        cold.join(",")
    );
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let p = |i: usize| PathBuf::from(&a[i]);
    match a[1].as_str() {
        "build" => cmd_build(&p(2), &p(3)),
        "payload" => cmd_payload(&p(2), &p(3)),
        "genq" => cmd_genq(&p(2), &p(3), a[4].parse().unwrap(), a[5].parse().unwrap()),
        "bench" => cmd_bench(&p(2), &p(3), &a[4]),
        c => panic!("unknown subcommand {c}"),
    }
}
