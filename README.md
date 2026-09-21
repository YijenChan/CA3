# CA3

CA3 is an evidence-gated system for progressive APT investigation over a
Forensic Memory Graph (FMG). It combines a calibrated statistical detector
with hierarchical Lead/Assistant reasoning and a deterministic Controller.
Agent hypotheses are recorded in an append-only Investigation Ledger; only
witnessed evidence can alter committed FMG state or the final attack-summary
graph.

This repository is the public implementation and protocol artifact for
**“CA3: Progressive APT Investigation Using a Forensic Memory Graph.”**

## What is included

- CDM 18 parsing and a queryable provenance graph store;
- complexity-bounded provenance intervals and detector feature construction;
- group-masked prediction, residual calibration, and bounded candidate selection;
- incremental FMG construction, frontier scheduling, and backbone validation;
- Lead/Assistant contracts, deterministic Controller logic, and round artifacts;
- frozen RQ2 canonical matching and RQ3 progressive-investigation protocols;
- a local browser UI with a clearly marked synthetic demonstration bundle.

DARPA Transparent Computing data, ORTHRUS labels, third-party baseline code,
model credentials, and unpublished run outputs are intentionally not included.
The public implementation is aligned with the manuscript interfaces and
protocols; it is not a bit-for-bit export of the isolated experiment machine.

## Installation

CA3 targets Python 3.11--3.12. The paper experiments used Python 3.12,
PyTorch 2.5.1, and two NVIDIA RTX 3090 GPUs.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[dev,graph]"
pytest
```

## Data preparation

Obtain DARPA TC E3/E5 data and fine-grained labels from their respective
owners. Do not commit either to this repository. A typical local workflow is:

```bash
python scripts/build_graph_store.py --help
python scripts/build_communities.py --help
```

The parser preserves raw evidence references, timestamps, endpoint UUIDs, and
typed event relations. Dataset-specific paths belong in an untracked local
configuration file. `configs/cdm18_semantics.toml` contains only the shared,
non-secret event taxonomy.

## Method-to-code map

| Manuscript component | Public implementation |
|---|---|
| Collector / bounded PG construction | `ca3.cdm18`, `ca3.graph_store`, `ca3.collector` |
| Node signatures and calibrated detector | `ca3.detector_features`, `ca3.masked_detector`, `ca3.causal_residual`, `ca3.detector_selection` |
| FMG construction and update | `ca3.fmg`, `ca3.incremental_fmg` |
| Lead/Assistant investigation | `ca3.hierarchical_investigation`, `ca3.protocol`, `ca3.bounded_context` |
| Evidence gate and progressive control | `ca3.backbone_validation`, `ca3.frontier`, `ca3.progressive_control` |
| Ledger and auditable run artifacts | `ca3.investigation`, `ca3.round_artifacts`, `ca3.metered_api` |

The detailed alignment and remaining reproduction inputs are recorded in
[`docs/METHODOLOGY_ALIGNMENT.md`](docs/METHODOLOGY_ALIGNMENT.md).

## Evaluation protocols

- [`artifacts/protocols/rq2_canonical_evaluation.md`](artifacts/protocols/rq2_canonical_evaluation.md)
  fixes canonical node/edge equality, temporal eligibility, one-to-one campaign
  matching, and macro aggregation for Node-Jac and Edge-Jac.
- [`artifacts/protocols/rq3_progressive_evaluation.md`](artifacts/protocols/rq3_progressive_evaluation.md)
  fixes 30-minute windows, blind historical access, `Fixed-k`, recomputation,
  oracle depth, and terminal-scope evaluation.

Machine-readable YAML versions are stored beside both documents. Per-run result
manifests should be exported using the fields listed in `artifacts/README.md`.

## Local system UI

The bundled UI can be inspected without data or an API key:

```bash
python -m system.ca3_system.serve
```

Open `http://127.0.0.1:8765`. The bundled trace is synthetic and demonstrates
the data contract only. To render an authorized local run, pass an untracked
adapter configuration:

```bash
python -m system.ca3_system.serve --config path/to/local_case.json
```

## LLM configuration and secrets

The manuscript identifies the exact base model used for reported experiments.
The implementation does not silently substitute another model. Supply the
model identifier in the run configuration and provide credentials through an
environment variable or a local untracked file. Never commit API keys.

## Reproducibility boundary

Reported tables were produced on an isolated experiment machine. The following
must accompany any archival result release before a third party can reproduce
the exact numbers: dataset/label checksums, trajectory manifests, frozen split
records, model response metadata, per-run terminal graphs, and the evaluated
commit hash. The protocol files define these fields without fabricating or
backfilling unavailable outputs.

## Citation

Please cite the accompanying paper. A final BibTeX entry will be added after
publication metadata is assigned.
