# RQ2 Canonical Evaluation Protocol

Status: frozen from the protocol reported by the experiment assistant on 2026-09-21.

This document is the human-readable companion to
`RQ2_CANONICAL_EVALUATION_PROTOCOL.yaml`. It records the evaluation semantics
used for Node-Jac and Edge-Jac without inferring unavailable implementation
paths or hashes.

## Ground-truth graphs

Ground-truth campaigns are constructed from the ORTHRUS fine-grained labels
and the fixed campaign intervals provided by the dataset or label files. A
ground-truth node is a concrete attack-labeled entity instance. A support or
bridge entity is included only when the ground-truth labels explicitly identify
it as attack-related; an entity recovered solely by CA3 or a baseline is never
added to the ground truth.

For each campaign, the ground-truth edge set contains every directed, typed
provenance edge whose endpoints are both in its ground-truth node set and whose
timestamp lies in the predefined campaign interval. Repeated canonical edges
are deduplicated.

## Canonical graphs

A canonical node maps to a concrete provenance-graph entity instance and is
identified by `(host, raw entity ID/UUID)`. A canonical edge is the directed,
typed tuple `(source, relation type, target)`. Original provenance event types
are normalized to a fixed shared relation taxonomy. Timestamps do not enter
node or edge equality; they are used only to constrain campaign matching.

FLASH, KAIROS, ORTHRUS, and CA3 use the same canonicalization, matching, and
metric implementation.

## Campaign matching

A predicted graph and a ground-truth campaign are eligible for matching only
when their evidence-time intervals have a non-empty overlap. Eligible pairs are
matched with maximum-weight one-to-one bipartite matching. Pair weight is the
cardinality of their canonical-node intersection, so the assignment maximizes
the total canonical-node intersection. Ties are resolved first by larger
temporal overlap and then by stable campaign and prediction identifiers;
Edge-Jac is not inspected during matching.

## Metrics and aggregation

Node-Jac is the Jaccard overlap of canonical node sets. Edge-Jac is the Jaccard
overlap of deduplicated directed, typed canonical edge sets. Within each run,
the two metrics are macro-averaged over matched pairs and unmatched graphs;
each unmatched prediction and each unmatched ground-truth campaign contributes
a score of zero. Matching and scoring are performed independently for every
run, after which run-level metrics are averaged.

## Files still required for the public artifact

The following files must be exported from the experiment environment before
the GitHub artifact is released:

- the shared relation-taxonomy mapping;
- per-dataset campaign identifiers and evidence-time boundaries;
- the canonicalization, matching, and metric scripts with a code commit;
- per-run matching assignments and metric records; and
- checksums for the released configuration and result files.

