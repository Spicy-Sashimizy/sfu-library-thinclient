//! Write guard (owner requirement 2026-09-29): the only way to obtain a
//! writable shard is through `check_writable`, called first by
//! `Shard::open`, `synth::build`, `plsim::materialize` and `plsim::restore`.
//! Refuses (non-zero exit via the CLI) unless ALL hold:
//! 1. the canonical target is under the allow-list root
//!    `/home/vscode/work/inplace_update/` (or $INPLACE_ALLOW_ROOT, which must
//!    itself be under that root);
//! 2. it is not, and is not inside, a protected root: `<repo>/data/`,
//!    `/var/tmp/seismic_stage`, every `mmap_dir` named by
//!    `/var/tmp/seismic_stage/staged_manifest.json` and by the manifest in
//!    `$SFU_SEISMIC_SHARD_MANIFEST`;
//! 3. no entry of the target dir is a symlink, and no regular file has more
//!    than one hard link (a hard link or symlink could alias a protected
//!    file; any alias is refused, stricter than checking the alias target);
//! 4. the target is on a local filesystem (allow-list of fs types from
//!    /proc/mounts, longest mount-point prefix);
//! 5. the target contains `.inplace_work_copy`, a JSON object whose `path`
//!    (this crate) or `dst` (the encoder's converter, FORMAT_V3 revision 5)
//!    equals the canonical target path (a copied dir carries its source's
//!    sentinel and is refused until the copier writes its own).

use std::path::{Path, PathBuf};

use crate::util::{err, Result};

pub const ALLOW_ROOT: &str = "/home/vscode/work/inplace_update";
pub const SENTINEL: &str = ".inplace_work_copy";
pub const LOCAL_FS: [&str; 8] = ["ext4", "ext3", "xfs", "btrfs", "overlay", "tmpfs", "f2fs", "zfs"];

fn repo_root() -> PathBuf {
    let m = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    m.join("../../..").canonicalize().unwrap_or_else(|_| PathBuf::from("/workspaces/sfu-library-thinclient"))
}

fn collect_mmap_dirs(v: &serde_json::Value, out: &mut Vec<PathBuf>) {
    match v {
        serde_json::Value::Object(m) => {
            for (k, x) in m {
                if k == "mmap_dir" {
                    if let Some(s) = x.as_str() {
                        out.push(PathBuf::from(s));
                    }
                }
                collect_mmap_dirs(x, out);
            }
        }
        serde_json::Value::Array(a) => a.iter().for_each(|x| collect_mmap_dirs(x, out)),
        _ => {}
    }
}

/// Every protected root (canonicalised where it exists).
pub fn protected_roots() -> Vec<PathBuf> {
    let repo = repo_root();
    let mut roots = vec![repo.join("data"), PathBuf::from("/workspaces/sfu-library-thinclient/data"), PathBuf::from("/var/tmp/seismic_stage")];
    let mut manifests = vec![PathBuf::from("/var/tmp/seismic_stage/staged_manifest.json")];
    if let Ok(m) = std::env::var("SFU_SEISMIC_SHARD_MANIFEST") {
        if !m.is_empty() {
            let p = PathBuf::from(&m);
            manifests.push(if p.is_absolute() { p } else { repo.join(p) });
        }
    }
    for m in manifests {
        if let Ok(b) = std::fs::read(&m) {
            if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&b) {
                let mut dirs = Vec::new();
                collect_mmap_dirs(&v, &mut dirs);
                for d in dirs {
                    roots.push(if d.is_absolute() { d } else { repo.join(d) });
                }
            }
        }
    }
    roots.into_iter().map(|r| r.canonicalize().unwrap_or(r)).collect()
}

/// Filesystem type of the longest mount point containing `p`.
pub fn fs_type_of(p: &Path) -> Option<String> {
    let mounts = std::fs::read_to_string("/proc/mounts").ok()?;
    let mut best: Option<(usize, String)> = None;
    for line in mounts.lines() {
        let f: Vec<&str> = line.split_whitespace().collect();
        if f.len() < 3 {
            continue;
        }
        let mp = f[1].replace("\\040", " ");
        if p.starts_with(&mp) && best.as_ref().map_or(true, |(l, _)| mp.len() > *l) {
            best = Some((mp.len(), f[2].to_string()));
        }
    }
    best.map(|b| b.1)
}

pub fn is_local_fs(p: &Path) -> bool {
    fs_type_of(p).map_or(false, |t| LOCAL_FS.contains(&t.as_str()))
}

fn allow_root() -> Result<PathBuf> {
    let base = PathBuf::from(ALLOW_ROOT).canonicalize().unwrap_or_else(|_| PathBuf::from(ALLOW_ROOT));
    match std::env::var("INPLACE_ALLOW_ROOT") {
        Ok(r) if !r.is_empty() => {
            let r = PathBuf::from(r).canonicalize().unwrap_or_else(|_| PathBuf::from(""));
            if !r.starts_with(&base) {
                return err(format!("GUARD: INPLACE_ALLOW_ROOT {r:?} is not under {base:?}"));
            }
            Ok(r)
        }
        _ => Ok(base),
    }
}

/// Path checks shared by existing and to-be-created targets.
fn check_path(canon: &Path) -> Result<()> {
    let allow = allow_root()?;
    if !canon.starts_with(&allow) || canon == allow {
        return err(format!("GUARD: refusing {canon:?}: not under the allow-list root {allow:?}"));
    }
    for r in protected_roots() {
        if canon.starts_with(&r) {
            return err(format!("GUARD: refusing {canon:?}: inside protected root {r:?}"));
        }
    }
    if !is_local_fs(canon) {
        return err(format!("GUARD: refusing {canon:?}: filesystem {:?} is not local", fs_type_of(canon)));
    }
    Ok(())
}

/// The single gate for every write path. `dir` must exist.
pub fn check_writable(dir: &Path) -> Result<PathBuf> {
    let canon = dir.canonicalize().map_err(|e| crate::util::Error::Msg(format!("GUARD: cannot canonicalise {dir:?}: {e}")))?;
    check_path(&canon)?;
    for e in std::fs::read_dir(&canon)? {
        let e = e?;
        let md = std::fs::symlink_metadata(e.path())?;
        if md.file_type().is_symlink() {
            return err(format!("GUARD: refusing {canon:?}: {:?} is a symlink", e.file_name()));
        }
        if md.is_file() && std::os::unix::fs::MetadataExt::nlink(&md) > 1 {
            return err(format!("GUARD: refusing {canon:?}: {:?} has {} hard links", e.file_name(), std::os::unix::fs::MetadataExt::nlink(&md)));
        }
    }
    let s = std::fs::read(canon.join(SENTINEL)).map_err(|_| crate::util::Error::Msg(format!("GUARD: refusing {canon:?}: no {SENTINEL} sentinel")))?;
    let v: serde_json::Value = serde_json::from_slice(&s).map_err(|_| crate::util::Error::Msg(format!("GUARD: refusing {canon:?}: unreadable sentinel")))?;
    let named = v.get("path").or_else(|| v.get("dst")).and_then(|x| x.as_str());
    if named != Some(canon.to_str().unwrap_or("")) || v.get("dst").and_then(|x| x.as_str()).is_some_and(|d| d != canon.to_str().unwrap_or("")) {
        return err(format!("GUARD: refusing {canon:?}: sentinel names {:?}", named));
    }
    Ok(canon)
}

/// Check a directory that is about to be created (its parent must exist).
pub fn check_new_dir(dir: &Path) -> Result<PathBuf> {
    let mut existing = dir.to_path_buf();
    let mut rest: Vec<std::ffi::OsString> = Vec::new();
    while !existing.exists() {
        rest.push(existing.file_name().ok_or_else(|| crate::util::Error::Msg("GUARD: bad path".into()))?.to_owned());
        existing = existing.parent().ok_or_else(|| crate::util::Error::Msg("GUARD: no existing ancestor".into()))?.to_path_buf();
    }
    let mut canon = existing.canonicalize()?;
    for r in rest.iter().rev() {
        canon.push(r);
    }
    check_path(&canon)?;
    Ok(canon)
}

/// Write the sentinel for `dir` (used by the crate's synthetic builder and
/// the harness copy step; the source manifest FNV is recorded).
pub fn write_sentinel(dir: &Path, source_manifest_fnv: &str) -> Result<()> {
    let canon = dir.canonicalize()?;
    check_path(&canon)?;
    let v = serde_json::json!({"path": canon.to_str().unwrap(), "dst": canon.to_str().unwrap(), "source_manifest_fnv64": source_manifest_fnv,
                                "written_by": "inplace_updater"});
    std::fs::write(canon.join(SENTINEL), serde_json::to_vec_pretty(&v)?)?;
    Ok(())
}
