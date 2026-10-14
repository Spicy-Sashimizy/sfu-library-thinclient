"""Peak memory of the fold dump stage alone (doc 10 F4 diagnosis, 2026-10-04).
Usage: probe_delta_ingest_fold_dump_mem.py <workers> <out.jsonl on local disk>; reads the local f16 twin of shard 0."""
import os, sys, time, json, threading
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "source")]
from spike.delta_ingest.foldin import dump_fold_jsonl

def tree(pid):
    kids = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                st = Path(f"/proc/{p}/stat").read_text()
                kids.setdefault(int(st.rsplit(")", 1)[1].split()[1]), []).append(int(p))
            except Exception:
                pass
    todo, out = [pid], []
    while todo:
        c = todo.pop(); todo.extend(kids.get(c, []))
        try:
            d = {}
            for ln in Path(f"/proc/{c}/status").read_text().splitlines():
                k = ln.split(":")[0]
                if k in ("VmRSS", "RssAnon", "RssFile", "RssShmem", "VmSwap"):
                    d[k] = int(ln.split()[1]) / 1048576
            pss = 0
            for ln in Path(f"/proc/{c}/smaps_rollup").read_text().splitlines():
                if ln.startswith("Pss:"):
                    pss = int(ln.split()[1]) / 1048576
            d["Pss"] = pss
            out.append(d)
        except Exception:
            pass
    return out

workers = int(sys.argv[1]); out = Path(sys.argv[2])
peak = {"tree_vmrss": 0, "tree_anon": 0, "tree_file": 0, "tree_pss": 0, "one_vmrss": 0}
stop = threading.Event()
def poll():
    while not stop.is_set():
        t = tree(os.getpid())
        s = lambda k: sum(x.get(k, 0) for x in t)
        peak["tree_vmrss"] = max(peak["tree_vmrss"], s("VmRSS") + s("VmSwap"))
        peak["tree_anon"] = max(peak["tree_anon"], s("RssAnon"))
        peak["tree_file"] = max(peak["tree_file"], s("RssFile"))
        peak["tree_pss"] = max(peak["tree_pss"], s("Pss"))
        peak["one_vmrss"] = max(peak["one_vmrss"], max((x.get("VmRSS", 0) for x in t), default=0))
        stop.wait(1)
th = threading.Thread(target=poll, daemon=True); th.start()
r = dump_fold_jsonl(Path("/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap"), set(), [], out, workers=workers)
stop.set(); th.join()
print(json.dumps({"workers": workers, "dump": r, "peak_gib": {k: round(v, 2) for k, v in peak.items()}}))
