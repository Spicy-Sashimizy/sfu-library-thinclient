#!/usr/bin/env bash
# SEISMIC 150M RAM-vs-latency sweep: step the container memory cap down, measure
# warm/cold p50 at each level. Page cache shrinks with the cap -> traces the knee
# where the ~40GB working set stops fitting. Qdrant stays stopped (SEISMIC-only).
set -u
C=claudebox-sfu-library-thinclient-app
REPO=/workspaces/sfu-library-thinclient
MANIFEST=data/eval_results/seismic_c25_shards_150m_mmap.json
Q=12; P=2
LEVELS="48 42 36 30 24 18"
SUM=/tmp/seismic_ram_sweep_summary.tsv

docker exec -u root $C bash -lc "printf 'mem_cap_gb\twarm_p50_ms\tcold_p50_ms\twarm_trav_ms\tvmrss_peak_gb\tvmswap_gb\tstatus\n' > $SUM"

for L in $LEVELS; do
  echo "=== LEVEL ${L}GB  ($(date -u +%H:%M:%S)) ==="
  docker update --memory=${L}g --memory-swap=${L}g $C >/dev/null 2>&1 || echo "  (update failed)"
  # fair cold start: best-effort drop page cache (host knob may be RO -> ignore)
  docker exec -u root $C bash -lc 'sync; echo 1 > /proc/sys/vm/drop_caches 2>/dev/null || true'
  RF=/tmp/sweep_${L}gb.json
  docker exec -u root $C bash -lc "cd $REPO && \
    SFU_SEISMIC_QUERY_CUT=10 SFU_SEISMIC_HEAP_FACTOR=0.8 SFU_SEISMIC_LOAD_MODE=mmap \
    .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --queries $Q --passes $P --shard-manifest $MANIFEST --result-file $RF \
    > /tmp/sweep_${L}gb.log 2>&1"
  RC=$?
  docker exec -u root $C bash -lc "cd $REPO && .venv/bin/python3 - $RF $L $RC >> $SUM 2>&1 <<'PY'
import json,sys
rf,L,rc=sys.argv[1],sys.argv[2],sys.argv[3]
try:
    d=json.load(open(rf)); s=d['seismic']; r=s['ram']; lt=s['latency_ms']; t=s['traverse_ms']
    w=round(lt['warm']['p50_ms']); c=round(lt['cold']['p50_ms']); tr=round(t['warm']['p50_ms'])
    print('%s\t%s\t%s\t%s\t%s\t%s\tOK' % (L,w,c,tr,r['vmrss_peak_gb'],r['vmswap_gb']))
except Exception as e:
    print('%s\t-\t-\t-\t-\t-\tFAIL(rc=%s):%s' % (L,rc,str(e)[:40]))
PY"
  echo "  level ${L}GB done (rc=$RC)"
  docker exec -u root $C bash -lc "tail -1 $SUM"
done

echo "=== restore container to no practical limit (54g) ==="
docker update --memory=54g --memory-swap=54g $C >/dev/null 2>&1
echo "=== SWEEP COMPLETE ==="
docker exec -u root $C bash -lc "cat $SUM"
