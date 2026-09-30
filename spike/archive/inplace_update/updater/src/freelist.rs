//! `forward_free.bin` (FORMAT_V3 §3.4): forward-heap holes by size class.

use crate::util::{err, fnv1a64, u32_at, u64_at, Result};

pub const FREE_MAGIC: u64 = u64::from_le_bytes(*b"SFUFFL3\0");
pub const FREE_CLASSES: [(u32, u32); 16] = [
    (1, 8), (9, 12), (13, 16), (17, 20), (21, 24), (25, 28), (29, 32), (33, 40),
    (41, 48), (49, 64), (65, 96), (97, 128), (129, 192), (193, 256), (257, 512),
    (513, 65535),
];
pub const FREE_HEADER: usize = 64;
pub const FREE_TABLE: usize = 16 * 32;

/// One hole: a whole dead row's record extent.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Hole {
    pub start: u32,
    pub len: u16,
    pub epoch: u16,
}

impl Hole {
    pub fn pack(&self) -> u64 {
        (self.start as u64) | ((self.len as u64) << 32) | (((self.epoch as u64) & 0x7FFF) << 48)
    }
    pub fn unpack(w: u64) -> Hole {
        Hole { start: (w & 0xFFFF_FFFF) as u32, len: ((w >> 32) & 0xFFFF) as u16, epoch: ((w >> 48) & 0x7FFF) as u16 }
    }
}

pub fn class_of(len: u32) -> usize {
    FREE_CLASSES.iter().position(|&(lo, hi)| len >= lo && len <= hi).expect("record length 0 has no class")
}

#[derive(Debug, Clone, Default)]
pub struct FreeList {
    pub epoch: u64,
    pub holes: Vec<Hole>,
}

impl FreeList {
    pub fn serialize(&self) -> Vec<u8> {
        let mut by_class: Vec<Vec<u64>> = vec![Vec::new(); 16];
        let mut hs = self.holes.clone();
        hs.sort();
        for h in &hs {
            by_class[class_of(h.len as u32)].push(h.pack());
        }
        let total: usize = by_class.iter().map(|v| v.len()).sum();
        let mut buf = vec![0u8; FREE_HEADER + FREE_TABLE + 8 * total];
        buf[0..8].copy_from_slice(&FREE_MAGIC.to_le_bytes());
        buf[8..12].copy_from_slice(&3u32.to_le_bytes());
        buf[12..16].copy_from_slice(&16u32.to_le_bytes());
        buf[16..24].copy_from_slice(&self.epoch.to_le_bytes());
        buf[24..32].copy_from_slice(&(total as u64).to_le_bytes());
        buf[32..40].copy_from_slice(&(total as u64).to_le_bytes());
        let ck = fnv1a64(&buf[0..56]);
        buf[56..64].copy_from_slice(&ck.to_le_bytes());
        let mut off = FREE_HEADER + FREE_TABLE;
        for (i, (lo, hi)) in FREE_CLASSES.iter().enumerate() {
            let o = FREE_HEADER + 32 * i;
            let n = by_class[i].len() as u64;
            buf[o..o + 4].copy_from_slice(&lo.to_le_bytes());
            buf[o + 4..o + 8].copy_from_slice(&hi.to_le_bytes());
            buf[o + 8..o + 16].copy_from_slice(&n.to_le_bytes());
            buf[o + 16..o + 24].copy_from_slice(&n.to_le_bytes());
            buf[o + 24..o + 32].copy_from_slice(&(off as u64).to_le_bytes());
            for &e in &by_class[i] {
                buf[off..off + 8].copy_from_slice(&e.to_le_bytes());
                off += 8;
            }
        }
        buf
    }

    pub fn parse(buf: &[u8]) -> Result<FreeList> {
        if buf.len() < FREE_HEADER + FREE_TABLE {
            return err("forward_free.bin too short");
        }
        if u64_at(buf, 0) != FREE_MAGIC || u32_at(buf, 8) != 3 || u32_at(buf, 12) != 16 {
            return err("forward_free.bin bad magic/version");
        }
        if u64_at(buf, 56) != fnv1a64(&buf[0..56]) {
            return err("forward_free.bin header checksum mismatch");
        }
        let epoch = u64_at(buf, 16);
        let total = u64_at(buf, 24) as usize;
        let mut holes = Vec::with_capacity(total);
        let mut seen = 0usize;
        for i in 0..16 {
            let o = FREE_HEADER + 32 * i;
            let (lo, hi) = (u32_at(buf, o), u32_at(buf, o + 4));
            if (lo, hi) != FREE_CLASSES[i] {
                return err("forward_free.bin class table mismatch");
            }
            let n = u64_at(buf, o + 8) as usize;
            let off = u64_at(buf, o + 24) as usize;
            if off + 8 * n > buf.len() {
                return err("forward_free.bin entries out of bounds");
            }
            for k in 0..n {
                let h = Hole::unpack(u64_at(buf, off + 8 * k));
                if class_of(h.len as u32) != i {
                    return err(format!("forward_free.bin hole of len {} in class {i}", h.len));
                }
                holes.push(h);
            }
            seen += n;
        }
        if seen != total {
            return err("forward_free.bin count mismatch");
        }
        Ok(FreeList { epoch, holes })
    }
}
