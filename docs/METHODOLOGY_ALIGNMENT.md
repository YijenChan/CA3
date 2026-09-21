# Manuscript-to-implementation alignment

## Collector

`cdm18.py`, `graph_schema.py`, and `graph_store.py` parse CDM 18 records and
preserve canonical UUIDs, directed typed events, timestamps, and raw-evidence
references. `collector.py` implements half-open time windows with recursive
node-budget splitting. This corresponds to the paper's complexity-bounded PGs.

## Detector

`detector_features.py` constructs context/target node signatures.
`masked_detector.py` implements group-masked shallow prediction.
`causal_residual.py` fits shrinkage-calibrated residual statistics, and
`detector_selection.py` applies percentile thresholds and bounded topology
expansion. Labels are consumed by evaluation code, not detector fitting.

## FMG and investigation

`fmg.py` stores communities, witnessed inter-community relations, and activation
tiers. `incremental_fmg.py` activates historical intervals without rewriting
forensic facts. The Lead and Assistant exchange typed proposals and bounded
verification tasks through `protocol.py`; `backbone_validation.py` and
`progressive_control.py` implement deterministic evidence and stopping gates.

## Public-release differences

- Workstation-only D:-drive guards were removed; all paths are caller supplied.
- Dataset-specific files, labels, intermediate graphs, and baseline checkouts
  are excluded.
- The UI's bundled trace is synthetic. Its JSON is an interface example, not an
  empirical result.
- Exact paper-number reproduction additionally requires the checksummed inputs
  and run manifests listed in `artifacts/README.md`.

These differences affect packaging and availability, not the paper's declared
method or evaluation definitions.
