"""Per-shard routing of delta docs (doc 10 §3 G2).

`route_shard(id)` is the rule that built the served plan01 base shards
(`scripts/seismic_testbed/shard_spool.py` `shard_id`: blake2b-8 of
seed + id, mod K). Re-implemented here dependency-free (shard_spool imports
the zstd spool reader at module import); `scripts/tests/test_foldin_gates.py`
asserts equality with the original on random ids.

Source-agnostic: any id string routes (W-ids, `arxiv:…`, `zotero:…`), so a
non-OpenAlex deployment folds by the same hash. The seed and K are dials
(`ROUTE_SEED`, `ROUTE_SHARDS`, `IngestLedger(route_seed=, route_shards=)`);
they must equal the rule that built the deployment's base shards.
"""
from __future__ import annotations

import hashlib

ROUTE_SEED = "sfu-seismic-plan01"
ROUTE_SHARDS = 8


def route_shard(doc_id: str, seed: str = ROUTE_SEED, n_shards: int = ROUTE_SHARDS) -> int:
    h = hashlib.blake2b((seed + str(doc_id)).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % n_shards
