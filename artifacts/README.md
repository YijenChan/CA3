# Artifact boundary

This directory contains frozen evaluation protocols, not paper result tables.
Raw datasets, private credentials, third-party baseline repositories, and
unpublished intermediate results are excluded.

For an archival run, retain at least:

- repository commit and environment lock/checksum;
- dataset, label, split, and configuration checksums;
- detector seed or LLM run identifier;
- prompt/model/response metadata and token accounting;
- RQ2 campaign matching pairs, unmatched graphs, and per-pair scores;
- RQ3 trajectory manifest, oracle depth, activated windows, checkpoint actions,
  terminal graph, stopping class, and Node-Jac/Edge-Jac;
- a machine-readable failure record for any excluded run.

Aggregate means must be derived from retained run-level records. Missing runs
must not be replaced with reconstructed or simulated values.
