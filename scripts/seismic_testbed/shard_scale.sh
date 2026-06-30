#!/usr/bin/env bash
# Corpus-size scaling: serve N of the 8 existing shards (N*18.8M docs), measure
# latency + working set. No rebuild — just sub-manifests of the C2 150M manifest.
set -u
cd /workspaces/sfu-library-thinclient
FULL=data/eval_results/seismic_c25_shards_150m_mmap.json
Q=40; P=2
SUM=/tmp/seismic_shard_scale_summary.tsv
printf "n_shards\tdocs_M\twarm_p50_ms\tcold_p50_ms\twarm_trav_ms\twarm_enc_ms\tvmrss_peak_gb\tvmswap_gb\n" > $SUM
for N in 1 2 4 8; do
  echo "=== N=$N shards ($(date -u +%H:%M:%S)) ==="
  .venv/bin/python3 -c "import json;m=json.load(open(\"$FULL\"));json.dump({\"n_shards\":$N,\"shards\":m[\"shards\"][:$N]},open(\"/tmp/_man_${N}.json\",\"w\"))"
  RF=/tmp/shardscale_${N}.json
  SFU_SEISMIC_QUERY_CUT=10 SFU_SEISMIC_HEAP_FACTOR=0.8 SFU_SEISMIC_LOAD_MODE=mmap \
    .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --queries $Q --passes $P --shard-manifest /tmp/_man_${N}.json --result-file $RF \
    > /tmp/shardscale_${N}.log 2>&1
  .venv/bin/python3 - $RF $N >> $SUM 2>&1 <<"PY"
import json,sys
rf,N=sys.argv[1],int(sys.argv[2])
try:
    d=json.load(open(rf)); s=d["seismic"]; r=s["ram"]; L=s["latency_ms"]; t=s["traverse_ms"]; e=s["encode_ms"]
    print("%d\t%.1f\t%d\t%d\t%d\t%d\t%s\t%s"%(N,N*18.8,round(L["warm"]["p50_ms"]),round(L["cold"]["p50_ms"]),round(t["warm"]["p50_ms"]),round(e["warm"]["p50_ms"]),r["vmrss_peak_gb"],r["vmswap_gb"]))
except Exception as ex:
    print("%d\t%.1f\tFAIL\t-\t-\t-\t-\t%s"%(N,N*18.8,str(ex)[:40]))
PY
  echo "  N=$N done"; tail -1 $SUM
done
echo "=== SHARD SCALE COMPLETE ==="; cat $SUM
