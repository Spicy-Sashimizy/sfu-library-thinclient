# data/ — runtime artifacts (mostly NOT in git)

- `seismic_150m/` — the served 8-shard SEISMIC index. **IRREPLACEABLE,
  READ-ONLY.** Never write/rename/relocate here; anything looks broken →
  STOP and surface it.
- `thinclient_index/` — meta.sqlite (24.9 GB, lazy-loads slowly on first
  touch), packed lexical, dense, spool. Heavy; don't scan casually over 9p.
- `eval_results/` — measurement evidence. Conventions in its README.md:
  family prefixes, `.INVALID`/`.SUPERSEDED` tagging, `archive/` policy.
  Canonical result JSONs are cited by docs BY PATH — never move one without
  repointing the citing doc in the same commit.
