"""Current-method group-masked predictor and disjoint residual/CDF calibration.

This module is separate from CP6-D4 so historical checkpoints remain replayable.
"""

from __future__ import annotations

import numpy as np
import torch
from sklearn.covariance import LedoitWolf
from torch import nn


def signature_groups(context_names, target_names):
    prefixes = ("behavior:", "role:", "temporal:", "structure:")
    groups = [[i for i, n in enumerate(target_names) if n.startswith(p)] for p in prefixes]
    flattened = [index for group in groups for index in group]
    if sorted(flattened) != list(range(len(target_names))) or not all(groups):
        raise ValueError("Every target must belong to exactly one nonempty group")
    masks = np.ones((4, len(context_names)), dtype=np.float32)
    for i, name in enumerate(context_names):
        if name.startswith(("incoming_relation:", "outgoing_relation:")):
            masks[0, i] = 0
            masks[1, i] = 0  # Direction-separated relation histograms proxy endpoint roles.
        if name.startswith("context:log_"):
            masks[3, i] = 0
    return groups, masks


class GroupMaskedPredictor(nn.Module):
    def __init__(self, context_names, target_names, hidden=64):
        super().__init__()
        self.groups, masks = signature_groups(context_names, target_names)
        self.register_buffer("masks", torch.tensor(masks))
        self.hidden = nn.Linear(len(context_names), hidden)
        self.heads = nn.ModuleList([nn.Linear(hidden, len(g)) for g in self.groups])
        self.output_dim = len(target_names)

    def forward(self, x):
        result = x.new_empty((len(x), self.output_dim))
        for i, (head, indices) in enumerate(zip(self.heads, self.groups)):
            result[:, indices] = head(torch.relu(self.hidden(x * self.masks[i])))
        return result

    def loss(self, predicted, target):
        return torch.stack(
            [nn.functional.smooth_l1_loss(predicted[:, g], target[:, g]) for g in self.groups]
        ).mean()


def fit_residual_models(residuals, types, n_min=128):
    if len(residuals) < 2 or not np.isfinite(residuals).all():
        raise ValueError("Insufficient or nonfinite residual fitting data")
    models = {}
    for key in [-1, *map(int, np.unique(types))]:
        rows = residuals if key == -1 else residuals[types == key]
        if key != -1 and len(rows) < n_min:
            continue
        lw = LedoitWolf().fit(rows.astype(np.float64))
        models[key] = {"center": lw.location_, "precision": lw.precision_, "n": len(rows)}
    return models


def residual_scores(residuals, types, models):
    contributions = np.empty_like(residuals, dtype=np.float64)
    for entity_type in np.unique(types):
        selected = types == entity_type
        m = models.get(int(entity_type), models[-1])
        centered = residuals[selected] - m["center"]
        contributions[selected] = centered * (centered @ m["precision"])
    return np.maximum(contributions.sum(axis=1), 0), contributions


def fit_cdfs(residuals, types, models, n_min=128):
    # Pool fallback scores must use the pooled covariance, not mixed type covariances.
    pooled, _ = residual_scores(residuals, types, {-1: models[-1]})
    cdfs = {-1: np.sort(pooled)}
    for t in map(int, np.unique(types)):
        selected = types == t
        if t in models and selected.sum() >= n_min:
            scores, _ = residual_scores(residuals[selected], types[selected], models)
            cdfs[t] = np.sort(scores)
    return cdfs


def calibrated_scores(residuals, types, models, cdfs):
    scores = np.empty(len(types))
    q = np.empty(len(types))
    contributions = np.empty_like(residuals, dtype=np.float64)
    for t in map(int, np.unique(types)):
        selected = types == t
        key = t if t in models and t in cdfs else -1
        s, a = residual_scores(residuals[selected], types[selected], {-1: models[key]})
        ref = cdfs[key]
        if not len(ref):
            raise ValueError("Empty calibration CDF")
        scores[selected], contributions[selected] = s, a
        q[selected] = np.searchsorted(ref, s, side="right") / len(ref)
    return scores, q, contributions


def select_per_pg(pg_ids, entity_ids, percentiles, *, threshold=0.95, fraction=0.075, cap=256):
    from collections import defaultdict
    from math import ceil

    grouped = defaultdict(list)
    for i, pg in enumerate(pg_ids):
        grouped[str(pg)].append(i)
    selected = np.zeros(len(pg_ids), dtype=bool)
    for indices in grouped.values():
        budget = min(cap, ceil(fraction * len(indices)))
        eligible = [i for i in indices if percentiles[i] >= threshold]
        eligible.sort(key=lambda i: (-percentiles[i], bytes(entity_ids[i])))
        selected[eligible[:budget]] = True
    return selected
