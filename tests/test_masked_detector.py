import numpy as np
import torch

from ca3.masked_detector import (
    GroupMaskedPredictor,
    calibrated_scores,
    fit_cdfs,
    fit_residual_models,
    select_per_pg,
)


def test_masked_channels_cannot_change_corresponding_predictions():
    model = GroupMaskedPredictor(
        ["self_type:x", "incoming_relation:r", "context:log_in_degree"],
        ["behavior:r", "role:subject", "temporal:span", "structure:in_degree"],
    )
    x = torch.zeros((2, 3))
    x[1, 1] = 999
    y = model(x)
    assert torch.allclose(y[0, :2], y[1, :2], rtol=0.0, atol=1e-7)
    x = torch.zeros((2, 3))
    x[1, 2] = 999
    assert torch.allclose(model(x)[0, 3], model(x)[1, 3], rtol=0.0, atol=1e-7)


def test_sparse_type_uses_consistent_pooled_model_and_cdf():
    rng = np.random.default_rng(7)
    fit = rng.normal(size=(100, 4))
    types = np.r_[np.zeros(98), [1, 1]]
    models = fit_residual_models(fit, types, n_min=10)
    cal = rng.normal(size=(50, 4))
    ct = np.zeros(50)
    cdfs = fit_cdfs(cal, ct, models, n_min=10)
    s, q, a = calibrated_scores(cal[:2], np.array([1, 99]), models, cdfs)
    assert np.allclose(s, a.sum(axis=1))
    assert np.all((q >= 0) & (q <= 1))
    assert 1 not in models and 99 not in cdfs


def test_empty_eligible_and_stable_ties():
    assert not select_per_pg(["p"] * 4, [b"d", b"c", b"b", b"a"], np.array([0.1] * 4)).any()
    selected = select_per_pg(["p"] * 4, [b"d", b"c", b"b", b"a"], np.ones(4), fraction=0.5)
    assert selected.tolist() == [False, False, True, True]
