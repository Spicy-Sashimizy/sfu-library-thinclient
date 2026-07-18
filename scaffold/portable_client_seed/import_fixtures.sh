#!/bin/sh
# Seed importer — run FROM the new portable-client repo root:
#   bash <oracle>/scaffold/portable_client_seed/import_fixtures.sh <oracle-root>
# Copies the pinned contract artifacts out of the oracle repo. Idempotent.
set -eu
ORACLE="${1:?usage: import_fixtures.sh <path-to-sfu-library-thinclient>}"
DATE=$(date -u +%Y-%m-%d)

mkdir -p fixtures/topk_goldens_${DATE} upstream_specs artifacts bundles

# 1. golden top-k fixtures (WI-4 method: ids+scores, native + v3, shards 1+2)
for f in wi4_topk_native_shard1.json wi4_topk_native_shard2.json \
         wi4_topk_v3_shard1.json wi4_topk_v3_shard2.json; do
  cp -v "$ORACLE/data/eval_results/$f" "fixtures/topk_goldens_${DATE}/"
done

# 2. the bundle-manifest contract example + updater reference implementation
cp -v "$ORACLE/data/eval_results/portable_stack_manifest.json" fixtures/
cp -v "$ORACLE/scripts/demo_dependability/portable_bundle_updater.py" upstream_specs/reference_updater.py

# 3. frozen spec snapshots (dated — this repo builds against THESE, see CONTRACT.md)
for d in PORTABLE_STACK_MANIFEST.md PORTABLE_DATA_SHIPPING_RESEARCH.md \
         GUI_BAREBONES_PROGRESS_SPEC.md WEBGUI_RELIABILITY_RESEARCH.md \
         GUI_INTERACTION_TESTBED_PLAN.md; do
  cp -v "$ORACLE/docs/infrastructure/$d" "upstream_specs/${d%.md}_snapshot_${DATE}.md"
done

# 4. seed docs into place (only if not already present)
SEED="$ORACLE/scaffold/portable_client_seed"
[ -f CLAUDE.md ] || cp -v "$SEED/CLAUDE.md" .
mkdir -p docs
[ -f docs/CONTRACT.md ] || cp -v "$SEED/CONTRACT.md" docs/
[ -f docs/BOOTSTRAP_PLAN.md ] || cp -v "$SEED/BOOTSTRAP_PLAN.md" docs/

echo ""
echo "Seed imported (fixture set ${DATE}). Next: BOOTSTRAP_PLAN.md Phase 0 step 2."
echo "REMINDER: pin the fixture-set date in docs/CONTRACT.md if it changed."
