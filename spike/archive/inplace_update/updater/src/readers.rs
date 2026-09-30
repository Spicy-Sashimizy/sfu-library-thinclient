//! `readers.bin` reader table (FORMAT_V3 revision 4; UPDATER_DESIGN.md
//! revision U1/U2). Slot (64 B): 0 pid (0 = free) | 8 epoch (u64::MAX = idle)
//! | 16 query start ns | 24 heartbeat ns (CLOCK_MONOTONIC) | 32 pid-namespace
//! id | 40 lease ns (0 = 600 s) | 48 boot id (first 8 bytes of
//! /proc/sys/kernel/random/boot_id) | 56 generation (incremented at each claim).

use std::fs::OpenOptions;
use std::path::Path;
use std::sync::atomic::{fence, AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use memmap2::{MmapMut, MmapOptions};

use crate::util::{err, Result};

pub const N_SLOTS: usize = 256;
pub const SLOT: usize = 64;
pub const IDLE: u64 = u64::MAX;
pub const DEFAULT_LEASE_NS: u64 = 600_000_000_000;

pub fn now_ns() -> u64 {
    let mut ts = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut ts) };
    ts.tv_sec as u64 * 1_000_000_000 + ts.tv_nsec as u64
}

pub fn pid_ns() -> u64 {
    std::fs::metadata("/proc/self/ns/pid").map(|m| std::os::unix::fs::MetadataExt::ino(&m)).unwrap_or(0)
}

pub fn boot_id() -> u64 {
    let s = std::fs::read_to_string("/proc/sys/kernel/random/boot_id").unwrap_or_default();
    let hex: String = s.chars().filter(|c| c.is_ascii_hexdigit()).take(16).collect();
    let b = u64::from_str_radix(&hex, 16).unwrap_or(0);
    b.swap_bytes()
}

/// The shared table, mapped MAP_SHARED.
pub struct Table {
    map: MmapMut,
}

unsafe impl Send for Table {}
unsafe impl Sync for Table {}

impl Table {
    pub fn open(path: &Path) -> Result<Table> {
        let f = OpenOptions::new().read(true).write(true).open(path)?;
        if f.metadata()?.len() != (N_SLOTS * SLOT) as u64 {
            return err("readers.bin has the wrong size");
        }
        Ok(Table { map: unsafe { MmapOptions::new().map_mut(&f)? } })
    }
    pub fn a(&self, slot: usize, field: usize) -> &AtomicU64 {
        unsafe { &*(self.map.as_ptr().add(slot * SLOT + field) as *const AtomicU64) }
    }

    /// Updater scan: the oldest epoch held by a live reader (None = no live
    /// reader). Dead slots are cleared (generation-checked CAS on pid) and counted.
    pub fn oldest(&self, cleared: &mut u64) -> Option<u64> {
        fence(Ordering::SeqCst);
        let my_ns = pid_ns();
        let my_boot = boot_id();
        let now = now_ns();
        let mut oldest: Option<u64> = None;
        for s in 0..N_SLOTS {
            let pid = self.a(s, 0).load(Ordering::SeqCst);
            if pid == 0 {
                continue;
            }
            let generation = self.a(s, 56).load(Ordering::SeqCst);
            let epoch = self.a(s, 8).load(Ordering::SeqCst);
            let ns = self.a(s, 32).load(Ordering::SeqCst);
            let hb = self.a(s, 24).load(Ordering::SeqCst);
            let lease = match self.a(s, 40).load(Ordering::SeqCst) {
                0 => DEFAULT_LEASE_NS,
                x => x,
            };
            let boot = self.a(s, 48).load(Ordering::SeqCst);
            let pid_dead = ns != 0 && ns == my_ns && unsafe { libc::kill(pid as i32, 0) } == -1
                && std::io::Error::last_os_error().raw_os_error() == Some(libc::ESRCH);
            let lease_dead = hb != 0 && now > hb && now - hb > lease;
            let boot_dead = boot != 0 && boot != my_boot;
            if pid_dead || lease_dead || boot_dead {
                if self.a(s, 56).load(Ordering::SeqCst) == generation
                    && self.a(s, 0).compare_exchange(pid, 0, Ordering::SeqCst, Ordering::SeqCst).is_ok()
                {
                    *cleared += 1;
                }
                continue;
            }
            if epoch == IDLE {
                continue;
            }
            oldest = Some(oldest.map_or(epoch, |o: u64| o.min(epoch)));
        }
        oldest
    }
}

/// A registered reader (claims one slot; heartbeat thread at lease/4).
pub struct ReaderGuard {
    table: Arc<Table>,
    pub slot: usize,
    pid: u64,
    generation: u64,
    stop: Arc<AtomicBool>,
    hb_thread: Option<std::thread::JoinHandle<()>>,
}

impl ReaderGuard {
    /// Claim a slot. `lease_ns` 0 = default; `heartbeat` false disables the
    /// background refresh (B7(c) reclaim trial).
    pub fn claim(table: Arc<Table>, lease_ns: u64, heartbeat: bool) -> Result<ReaderGuard> {
        let real_pid = std::process::id() as u64;
        for s in 0..N_SLOTS {
            if table.a(s, 0).compare_exchange(0, real_pid, Ordering::SeqCst, Ordering::SeqCst).is_ok() {
                let generation = table.a(s, 56).fetch_add(1, Ordering::SeqCst) + 1;
                table.a(s, 8).store(IDLE, Ordering::SeqCst);
                table.a(s, 32).store(pid_ns(), Ordering::SeqCst);
                table.a(s, 40).store(lease_ns, Ordering::SeqCst);
                table.a(s, 48).store(boot_id(), Ordering::SeqCst);
                table.a(s, 24).store(now_ns(), Ordering::SeqCst);
                let stop = Arc::new(AtomicBool::new(false));
                let hb_thread = if heartbeat {
                    let (t2, st2) = (table.clone(), stop.clone());
                    let period = (if lease_ns == 0 { DEFAULT_LEASE_NS } else { lease_ns }) / 4;
                    Some(std::thread::spawn(move || {
                        while !st2.load(Ordering::SeqCst) {
                            if t2.a(s, 0).load(Ordering::SeqCst) != real_pid || t2.a(s, 56).load(Ordering::SeqCst) != generation {
                                break;
                            }
                            t2.a(s, 24).store(now_ns(), Ordering::SeqCst);
                            let mut left = period;
                            while left > 0 && !st2.load(Ordering::SeqCst) {
                                let d = left.min(5_000_000);
                                std::thread::sleep(Duration::from_nanos(d));
                                left -= d;
                            }
                        }
                    }))
                } else {
                    None
                };
                return Ok(ReaderGuard { table, slot: s, pid: real_pid, generation, stop, hb_thread });
            }
        }
        err("readers.bin: no free slot")
    }

    /// Register epoch: store E, re-read the header, repeat until stable
    /// (plan 06 Addendum third). `published` reads the header.
    pub fn begin(&self, published: impl Fn() -> u64) -> Result<u64> {
        loop {
            let e1 = published();
            self.table.a(self.slot, 8).store(e1, Ordering::SeqCst);
            self.table.a(self.slot, 16).store(now_ns(), Ordering::SeqCst);
            fence(Ordering::SeqCst);
            let e2 = published();
            if e1 == e2 {
                self.check()?;
                return Ok(e1);
            }
        }
    }

    /// Fails if the slot was reclaimed (pid or generation changed).
    pub fn check(&self) -> Result<()> {
        if self.table.a(self.slot, 0).load(Ordering::SeqCst) != self.pid || self.table.a(self.slot, 56).load(Ordering::SeqCst) != self.generation {
            return err("reader slot reclaimed (pid/generation changed): result discarded");
        }
        Ok(())
    }

    /// Manual heartbeat (the decoder's per-term refresh rule).
    pub fn beat(&self) -> Result<()> {
        self.check()?;
        self.table.a(self.slot, 24).store(now_ns(), Ordering::SeqCst);
        Ok(())
    }

    /// End a query: verify the slot is still ours, then go idle.
    pub fn end(&self) -> Result<()> {
        let r = self.check();
        if r.is_ok() {
            self.table.a(self.slot, 8).store(IDLE, Ordering::SeqCst);
        }
        r
    }
}

impl Drop for ReaderGuard {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(h) = self.hb_thread.take() {
            let _ = h.join();
        }
        if self.table.a(self.slot, 0).load(Ordering::SeqCst) == self.pid && self.table.a(self.slot, 56).load(Ordering::SeqCst) == self.generation {
            self.table.a(self.slot, 8).store(IDLE, Ordering::SeqCst);
            let _ = self.table.a(self.slot, 0).compare_exchange(self.pid, 0, Ordering::SeqCst, Ordering::SeqCst);
        }
    }
}
