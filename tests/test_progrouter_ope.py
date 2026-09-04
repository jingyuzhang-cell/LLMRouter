import numpy as np

from progrouter_reproduction.ope import (
    dr_contributions,
    effective_sample_size,
    ips_contributions,
    paired_group_bootstrap,
    snips_value,
)


def test_dr_is_direct_model_when_no_actions_match():
    got = dr_contributions([0, 0], [1, 1], [1, 0], [.2, .3], [.7, .8])
    assert np.allclose(got, [.7, .8])


def test_dr_correction_uses_frozen_quarter_propensity():
    got = dr_contributions([1], [1], [1.0], [.5], [.5])
    assert np.allclose(got, [2.5])


def test_ips_snips_and_effective_sample_size():
    a = [0, 1, 2, 3]; pi = [0, 0, 2, 0]; y = [1, 0, .5, 0]
    assert np.allclose(ips_contributions(a, pi, y), [4, 0, 2, 0])
    assert snips_value(a, pi, y) == .75
    assert effective_sample_size(a, pi) == 2


def test_group_bootstrap_uses_group_means_not_rows():
    result = paired_group_bootstrap([1, 1, 0], [0, 0, 0], ["a", "a", "b"], replicates=100)
    assert result["groups"] == 2
    assert result["estimate"] == .5

