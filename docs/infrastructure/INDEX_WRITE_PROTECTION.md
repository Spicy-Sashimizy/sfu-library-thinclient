# Write protection and backup of the irreplaceable index (`data/seismic_150m/`)

**Status:** ACTIVE

**Written 2026-09-30** after the in-place update spike's first day
(`docs/archive/inplace_update/07_INPLACE_PAUSE_HANDOVER_2026-09-29.md` §6,
`docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md`; that spike closed 2026-09-30). The index (320 files, 200 GB,
newest file 2026-07-14) has NO second copy and its rebuild inputs are gone
(`THIN_CLIENT_SWAP.md` §Migration). This page records what protects it
today, what still does not, and the operator steps that close the gap.

## 1. State of the originals (verified 2026-09-30 00:21Z)

- All 320 files identical to the baseline listing taken 2026-09-29 20:15Z
  (size + mtime): `/home/vscode/work/inplace_update/baseline_20260929T2015Z/`.
- The 8 served dv-v2 shards (96 files, 5.55 GB each): sampled bytes (8 × 1 MiB
  per file, head, tail, 6 seeded offsets) identical to the staged copies in
  `/var/tmp/seismic_stage`, whose shards 1–7 were copied in July 2026.
- A full SHA-256 manifest is being produced under the latency lock
  (`/home/vscode/work/inplace_update/checksums/run_sha256.sh`); when it
  lands it is committed next to this page as `seismic_150m_sha256_<date>.txt`
  and is the reference for every later integrity check and for backup
  verification (`sha256sum -c`).
- **2026-09-29 (host-side manifest):** `seismic_150m_sha256_2026-09-29.txt`
  next to this page covers all 320 files of `data/seismic_150m/index/plan01`
  (186.2 GB), hashed on the Windows host from the drvfs originals 19:23–19:51
  PDT while the app container was stopped (no writer running). Paths are
  relative to `index/plan01/`. The in-container manifest, when it lands,
  should agree with it line for line. It was used to verify the §4C backup.

## 2. Incidents to date (none touched an original)

| Date | What | Cause | Fixed |
|---|---|---|---|
| 2026-09-29 before 08:54Z | staged COPY of shard 0 (`/var/tmp/seismic_stage`, 5.5 GB) deleted, re-copied from the original the same day | product bug in `_stage_shards_local` (`retriever.py`): source == destination → rmtree | yes, `585f3cab`, test `scripts/tests/test_seismic_shard_staging.py`, `CODE_INVARIANTS.md` |
| 2026-09-29 20:14Z | an empty probe file created and removed in `index/plan01/` by the coordinator's write test; the directory mtime now reads that date | operator error (assumed the directory was already read-only) | n/a |
| 2026-10-01 04:24Z | a new directory `data/seismic_150m/delta_should_not_exist/` holding an empty 60 KB `ledger.sqlite` was created by an agent's failing-first unit test for the O16 refusal and removed ~18 s later (same for `data/thinclient_index/delta/`); `data/seismic_150m/` mtime now reads that time; nothing under `index/` was read, changed or removed (checked 06:11Z: no entry under `index/` newer than 2026-09-30) | test used the real `data/` paths against the pre-fix CLI, which had no refusal | yes — tests run on a tmp data tree; the CLI now refuses a write root under `data/seismic_150m` (`resolve_delta_root`, 8520e6e2, 86b75786) |
| 2026-09-29 23:54Z | a baseline guard saw 721 / 406 protected files as MISSING and aborted two runs; minutes later all present and unchanged | transient stat failures on the 9p mount (cause unverified; cf. open issue O12) | guards now retry a MISSING file, abort at once on a CHANGED one (`1da6c0e5`, `08e507b5`) |

## 3. What protects the originals today

1. **Code guards** in the only two programs that write shard files
   (`spike/archive/inplace_update/updater` — `guard::check_writable`, first call of
   every open-for-write; the v2→v3 converter): refuse any canonical path
   inside `<repo>/data/`, `/var/tmp/seismic_stage`, or any `mmap_dir` of the
   staged / served manifests; refuse anything outside
   `/home/vscode/work/inplace_update/`; refuse symlinks, hard links
   (`nlink > 1`), non-local filesystems, and a directory without its own
   `.inplace_work_copy` sentinel. Tests: one per refusal case.
2. **Baseline check** before and after every measured run (size + mtime of
   `data/seismic_150m`, `data/thinclient_index`, `/var/tmp/seismic_stage`);
   a difference aborts the run.
3. **Filesystem permissions, partial:** `chmod a-w` succeeded on 215 of the
   320 files (2026-09-29); 105 files and every directory refused
   ("Operation not permitted" on the drvfs/9p mount). Undo:
   `find data/seismic_150m -type f -exec chmod u+w {} +`.
4. **Environment:** `SFU_SEISMIC_STAGE_DIR`, `SFU_META_STAGE_DIR`,
   `SFU_DELTA_ROOT` are set EMPTY in every experiment process (the repository
   `.env` re-inserts the stage directory, so unsetting is not enough).

What this does NOT give: OS-level enforcement. A process that ignores the
guards (a bug, a stray shell command) can still write to 105 files and can
create or delete files in every directory.

## 4. Operator steps that close the gap (one of A or B; C regardless)

Owner's decision 2026-09-30: runs that load the SERVING STACK with an
experiment shard (bars B3/B6 of the in-place spike, moot since that spike
closed MEASURED 2026-09-30) are held until A or B is
in place. Everything that writes only to copies continues.

### A. Read-only bind mount in THIS container (cheapest; needs a container restart)

Docker already mounts one host path read-only here
(`/mnt/claude-desktop-logs`, `ro` in `/proc/mounts`), so the same works for
the index. In your container's compose file (the owner's `.devcontainer/docker-compose.yml`, outside the repository), service `app`, add under
`volumes:` (after the workspace mount; a nested bind mount shadows the path):

```yaml
      - ../data/seismic_150m:/workspaces/sfu-library-thinclient/data/seismic_150m:ro
```

Then rebuild/restart the container. Verify inside:
`findmnt -T data/seismic_150m -o TARGET,OPTIONS` shows `ro`, and
`touch data/seismic_150m/x` fails with "Read-only file system". Serving is
unaffected: the index is only ever read; staging copies to
`/var/tmp/seismic_stage`, which stays writable. The `.devcontainer/*` files
currently carry uncommitted owner edits, so this change is the owner's to
make and commit.

### B. Host-level ACL (protects every container and the host itself)

On the Windows host, from an elevated PowerShell, with `<PATH>` = the
repository's `data\seismic_150m` folder:

```powershell
# deny write/delete/append to Everyone, recursively; reads stay allowed
icacls "<PATH>" /deny "*S-1-1-0:(OI)(CI)(W,D,DC,AD,WA,WEA)"
# verify: this must fail with "Access is denied"
echo x > "<PATH>\probe.txt"
```

Undo: `icacls "<PATH>" /remove:d "*S-1-1-0"`. Inside the container the
mount then returns EACCES on every write, including from processes that
bypass the code guards.

### C. Backup (the largest risk reducer; independent of the spike)

Recommended: `robocopy` (Windows) or `rsync -a` (Linux) of the whole
`data\seismic_150m` folder to a separate physical disk, then verify against
the SHA-256 manifest of §1:

```bash
cd <backup>/seismic_150m/index/plan01 && sha256sum -c <manifest> --quiet
```

**Backup made 2026-09-29 (a second copy now exists, on a DISCONNECTED drive).**

| | |
|---|---|
| What | `data/seismic_150m/index/plan01/` complete: 34 directories, 320 files, 186.228 GB (all 8 shards × f16 / dotvbyte / dotvbyte.e5 / dotvbyte.e5.v2, plus `e5_perms/`) |
| Where | USB SSD "bigass_ssd" (Realtek RTL9210 UAS bridge, 477 GB, NTFS; Windows drive letter F: when plugged into the host, usbipd bus 1-1), path `F:\sfu-library-thinclient-backup\data\seismic_150m\index\plan01\` |
| Alongside | `F:\docker-vhdx-backup\docker_data.vhdx` (Docker Desktop data disk, 274 GB allocated) — the drive is full (≈17 GB free); nothing else fits |
| How | `robocopy … /E /COPY:DAT /DCOPY:DAT /R:3 /W:10 /MT:8 /XJ`, 19:15–19:34 PDT, rc=1, log `F:\sfu-library-thinclient-backup\robocopy_plan01_2026-09-29.log`; taken while the app container was down for the Docker data-disk backup, so no writer could touch the source |
| Verified | robocopy `/L` re-listing: 0 copied / 0 mismatch / 0 failed / 0 extras. Independent SHA-256 of ALL 320 files on both sides (source 19:23–19:51, backup 19:34–20:16 PDT): **manifests identical line for line**. Manifest: `seismic_150m_sha256_2026-09-29.txt` (this folder) and `F:\sfu-library-thinclient-backup\seismic_150m_plan01_sha256_2026-09-29.txt` |
| Restore | plug the drive into the host (it appears as F:), `robocopy F:\sfu-library-thinclient-backup\data\seismic_150m\index\plan01 <repo>\data\seismic_150m\index\plan01 /E /COPY:DAT /DCOPY:DAT /R:3 /W:10`, then `cd data/seismic_150m/index/plan01 && sha256sum -c ../../../../docs/infrastructure/seismic_150m_sha256_2026-09-29.txt --quiet` |
| Not backed up | `data/thinclient_index/` (117.7 GB: meta.sqlite 24.9 GB, packed 41.9 GB, sections 52.3 GB) — no room on this drive; still single-copy |
| Caveat | the drive must NOT be attached into WSL via `usbipd attach --busid 1-1` while it holds these backups: that detaches F: from Windows |

Order of value if only one copy fits: the 8 served dv-v2 shards
(`global_shard{0..7}of8.dotvbyte.e5.v2.mmap`, 44.4 GB — already duplicated
in `/var/tmp/seismic_stage`, but that is container-local disk), then the 8
f16 twins (`global_shard{0..7}of8.mmap`, the rebuild source), then the older
formats.

## 5. Checks to run after any of the above

```bash
# nothing changed since the baseline
find data/seismic_150m -type f -printf '%s\t%T@\t%p\n' | sort -k3 \
  | diff -q - /home/vscode/work/inplace_update/baseline_20260929T2015Z/data_seismic_150m.tsv
# full content check (200 GB read; run under the latency lock)
flock /tmp/sfu_latency_measure.lock sha256sum -c docs/infrastructure/seismic_150m_sha256_<date>.txt --quiet
```
