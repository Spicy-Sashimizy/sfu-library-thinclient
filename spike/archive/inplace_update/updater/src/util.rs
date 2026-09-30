//! Small shared helpers: error type, FNV-1a-64, alignment, bit-field reads.

use std::fmt;

/// Error type for the updater. `Injected` marks a deliberate crash injected by
/// a test or by `--crash-after-op` (the caller must treat it as a crash: stop,
/// write nothing more, reopen).
#[derive(Debug)]
pub enum Error {
    Msg(String),
    Injected(u64),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Msg(m) => write!(f, "{m}"),
            Error::Injected(n) => write!(f, "injected crash after write op {n}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Error::Msg(format!("io: {e}"))
    }
}

impl From<serde_json::Error> for Error {
    fn from(e: serde_json::Error) -> Self {
        Error::Msg(format!("json: {e}"))
    }
}

pub type Result<T> = std::result::Result<T, Error>;

pub fn err<T>(m: impl Into<String>) -> Result<T> {
    Err(Error::Msg(m.into()))
}

/// FNV-1a 64 (the spec's checksum; identical to `inplace_v3::fnv1a64`).
pub fn fnv1a64(bytes: &[u8]) -> u64 {
    fnv1a64_cont(0xcbf2_9ce4_8422_2325, bytes)
}

/// Continue an FNV-1a 64 hash over more bytes (hash of a ‖ b).
pub fn fnv1a64_cont(mut h: u64, bytes: &[u8]) -> u64 {
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

pub fn align_up(cur: usize, a: usize) -> usize {
    cur + (a - cur % a) % a
}

/// LSB-first bit field read inside little-endian u64 words (toolkit layout).
#[inline]
pub fn get_bits(words: &[u64], bitpos: usize, width: usize) -> u64 {
    if width == 0 {
        return 0;
    }
    let w = bitpos >> 6;
    let o = bitpos & 63;
    let mut v = words[w] >> o;
    if o + width > 64 {
        v |= words[w + 1] << (64 - o);
    }
    if width == 64 { v } else { v & ((1u64 << width) - 1) }
}

pub fn u64_at(b: &[u8], o: usize) -> u64 {
    u64::from_le_bytes(b[o..o + 8].try_into().unwrap())
}

pub fn u32_at(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes(b[o..o + 4].try_into().unwrap())
}

/// Parse `"W<digits>"` into its numeric part.
pub fn parse_wid(s: &[u8]) -> Option<u64> {
    if s.len() < 2 || s[0] != b'W' || s.len() > 20 {
        return None;
    }
    let mut v: u64 = 0;
    for &c in &s[1..] {
        if !c.is_ascii_digit() {
            return None;
        }
        v = v.checked_mul(10)?.checked_add((c - b'0') as u64)?;
    }
    Some(v)
}
