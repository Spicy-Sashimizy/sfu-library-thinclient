//! Batch file `*.sfubat` (UPDATER_DESIGN.md §1).

use std::io::Write;
use std::path::Path;

use crate::util::{err, fnv1a64, u32_at, u64_at, Result};

pub const BATCH_MAGIC: u64 = u64::from_le_bytes(*b"SFUBAT1\0");
pub const OP_DELETE: u8 = 1;
pub const OP_UPSERT: u8 = 2;

#[derive(Debug, Clone, PartialEq)]
pub struct Rec {
    pub op: u8,
    pub id: u64,
    pub comps: Vec<u16>,
    pub vals: Vec<f32>,
}

fn pad(buf: &mut Vec<u8>, a: usize) {
    while buf.len() % a != 0 {
        buf.push(0);
    }
}

pub fn write_batch(path: &Path, recs: &[Rec]) -> Result<()> {
    let mut body = Vec::new();
    for r in recs {
        let start = body.len();
        body.push(r.op);
        body.extend_from_slice(&[0, 0, 0]);
        body.extend_from_slice(&(r.comps.len() as u32).to_le_bytes());
        body.extend_from_slice(&r.id.to_le_bytes());
        for c in &r.comps {
            body.extend_from_slice(&c.to_le_bytes());
        }
        while (body.len() - start) % 4 != 0 {
            body.push(0);
        }
        for v in &r.vals {
            body.extend_from_slice(&v.to_le_bytes());
        }
        pad(&mut body, 8);
    }
    let mut h = vec![0u8; 32];
    h[0..8].copy_from_slice(&BATCH_MAGIC.to_le_bytes());
    h[8..12].copy_from_slice(&1u32.to_le_bytes());
    h[16..24].copy_from_slice(&(recs.len() as u64).to_le_bytes());
    h[24..32].copy_from_slice(&fnv1a64(&body).to_le_bytes());
    let mut f = std::fs::File::create(path)?;
    f.write_all(&h)?;
    f.write_all(&body)?;
    f.sync_all()?;
    Ok(())
}

pub fn read_batch(path: &Path) -> Result<Vec<Rec>> {
    let b = std::fs::read(path)?;
    if b.len() < 32 || u64_at(&b, 0) != BATCH_MAGIC || u32_at(&b, 8) != 1 {
        return err("not a SFUBAT1 file");
    }
    let n = u64_at(&b, 16) as usize;
    let body = &b[32..];
    if fnv1a64(body) != u64_at(&b, 24) {
        return err("batch body checksum mismatch");
    }
    let mut out = Vec::with_capacity(n);
    let mut o = 0usize;
    for _ in 0..n {
        let start = o;
        let op = body[o];
        let nnz = u32_at(body, o + 4) as usize;
        let id = u64_at(body, o + 8);
        o += 16;
        let comps: Vec<u16> = (0..nnz).map(|i| u16::from_le_bytes([body[o + 2 * i], body[o + 2 * i + 1]])).collect();
        o += 2 * nnz;
        while (o - start) % 4 != 0 {
            o += 1;
        }
        let vals: Vec<f32> = (0..nnz).map(|i| f32::from_le_bytes(body[o + 4 * i..o + 4 * i + 4].try_into().unwrap())).collect();
        o += 4 * nnz;
        while o % 8 != 0 {
            o += 1;
        }
        if op != OP_DELETE && op != OP_UPSERT {
            return err(format!("bad op {op}"));
        }
        if id >= 1 << 63 {
            return err("id >= 2^63");
        }
        if !comps.windows(2).all(|w| w[0] < w[1]) {
            return err(format!("record {id}: components not strictly ascending"));
        }
        out.push(Rec { op, id, comps, vals });
    }
    Ok(out)
}
