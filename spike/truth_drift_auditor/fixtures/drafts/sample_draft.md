# Draft: storage notes (sample)

On the served social-sciences section the per-script zstd dictionaries reduce the stored abstract sidecar by 17.6 % relative to compressing the same blocks with no dictionary, a saving of about 2.37 GB.

Projected over the full 150M-work corpus the abstract sidecar is estimated at about 60 GB with dictionaries, which comfortably beats the earlier 64.7 GB figure.

Dictionary compression also makes decoding faster than the no-dictionary baseline, so it is a pure win for serving latency.

At 100 rows the Lance fetch was 1.72x slower than SQLite at p50 on the 20M-row fixture, so SQLite stays the default metadata store.

The pilot will be run on three writers during November and we expect it to be well received.
