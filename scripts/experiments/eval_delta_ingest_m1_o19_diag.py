#!/usr/bin/env python3
"""M1 2026-10-01 diagnostic: the one cross-commit difference (topic index 117) vs the
stored 2026-09-29 gate_off rows is reproduced by undoing ONLY the O19 lower-casing
(bm25f_query_text) in a process on the d985b70d snapshot. Paths are the 2026-10-01
scratch layout; run under flock -s with the stage dirs empty (see M1_FINDINGS.md)."""
import json, sys, time
sys.path.insert(0, "/home/vscode/work/delta_ingest/m1/code_d985b70d/src")
import lib.tools as tools
import lib.thinclient.retriever as rmod
g = json.load(open('/var/tmp/sfu_delta_A_20260929/gate_off.json'))['passes'][0]['rows'][117]
n = json.loads(open('/home/vscode/work/delta_ingest/m1/gate_off.rows.jsonl').readlines()[117])
q = g['query']
r = tools._get_thinclient_retriever()
r._fetch_remote_abstracts = lambda ids: {}
r._load()
dump = lambda o: json.dumps(o, sort_keys=True, default=str)
cur = dump(r.search_rrf(q, top_k=50))
print("current == today row:", cur == n['fused'], "== 09-29:", cur == g['fused'], flush=True)
orig = rmod.bm25f_query_text
rmod.bm25f_query_text = lambda s: "".join(c if c.isalnum() or c.isspace() else " " for c in s)
nolow = dump(r.search_rrf(q, top_k=50))
print("no-lowercase == 09-29:", nolow == g['fused'], "== today:", nolow == n['fused'], flush=True)
rmod.bm25f_query_text = orig
print("bm25f text:", repr(orig(q)), flush=True)
