# RQ3 Progressive Evaluation Protocol

Status: protocol frozen; the detailed trajectory manifest remains to be
exported from the experiment environment for the public artifact.

## Blind historical access

All four datasets use 30-minute windows. A trajectory starts from the latest
registered window containing a provisional campaign-associated seed. That
window is `W1` at expansion depth zero. Each Controller-approved
`extend_left` action activates exactly one immediately preceding window, so
`Wj` has expansion depth `j-1`.

Each checkpoint permits at most eight Lead/Assistant/Controller reasoning
rounds. This reasoning budget resets after a historical window is successfully
activated. The historical expansion budget is the complete registered sequence
of available preceding windows for the trajectory and must satisfy
`B_exp >= max(k, d*)`; it therefore cannot truncate Fixed-k or the oracle
boundary. This replaces the inconsistent draft entry `12 windows/24 h`:
30-minute windows require 48 expansions to cover 24 hours.

## Registered trajectories and oracle

One trajectory consists of a fixed campaign, a fixed late-stage seed window,
and an ordered sequence of preceding windows. A campaign is eligible only when
the Detector provides a registered late-stage seed and its label-defined entry
evidence occurs in an earlier available window. Campaign ID, seed, initial
window, preceding-window sequence, and oracle depth are fixed before inspecting
RQ3 results. The registered counts are three trajectories for E3-CADETS and two
each for E3-THEIA, E5-CADETS, and E5-ClearScope. Every trajectory is evaluated
over five independent LLM runs.

For each campaign, entry evidence is a predefined label-derived entity or
event. The offline oracle depth `d*` is the smallest expansion depth at which
the activated scope contains both that entry evidence and a directed,
temporally ordered witnessed path from it to the fixed initial seed. The oracle
uses labels and raw provenance only after execution and is never exposed to an
evaluated policy. It is fixed across the five LLM runs. Under the registered
indexing, the illustrated E3-THEIA trace stops at `W94`, hence `d*=93`; `W93`
remains insufficient.

## Reference policies

Fixed-k uses `k=48`, equivalent to a 24-hour lookback for 30-minute windows.
The value is selected on a disjoint development set by minimizing mean absolute
distance to development oracle depths. At test time it always stops after 48
backward expansions and does not inspect investigation state to choose its
stopping depth.

At every checkpoint, Recompute rebuilds the FMG, candidate/retained backbone,
Investigation Ledger, and reduced investigation state from all evidence then
activated. It does not reuse committed state from the preceding checkpoint.
It otherwise uses the same LLM, prompts, per-checkpoint reasoning budget,
evidence gates, and Controller stopping conditions as CA3.

All policies receive the same ordered sequence of available windows and the
same evidence at corresponding depths, but may terminate at different depths.
Exact, early, and delayed stops correspond to terminal depth equal to, less
than, and greater than `d*`, respectively; budget exhaustion is delayed. The
terminal graph is evaluated with Node-Jac and Edge-Jac.

## Public-artifact files still required

- the complete trajectory manifest, including realized `B_exp` and `d*`;
- the disjoint development split and Fixed-k selection record;
- per-checkpoint Controller traces for all five runs;
- per-run terminal graphs and stopping classifications; and
- code/configuration versions and checksums.

Earlier local 1--2 hour E3-CADETS pilots remain development records and are not
the source of the protocol or results reported in the manuscript.
