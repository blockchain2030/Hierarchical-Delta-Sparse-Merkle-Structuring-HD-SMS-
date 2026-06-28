"""Unit tests for the workload generator."""
import pytest

from simulation.workload_generator import MicroFractionWorkloadGenerator, WorkloadConfig


def test_constructor_rejects_invalid_config():
    with pytest.raises(ValueError):
        WorkloadConfig(account_count=0)
    with pytest.raises(ValueError):
        WorkloadConfig(intra_partition_ratio=1.5)


def test_workload_is_deterministic_under_same_seed():
    cfg_a = WorkloadConfig(seed=12345, epochs=3, poisson_lambda=10, account_count=100)
    cfg_b = WorkloadConfig(seed=12345, epochs=3, poisson_lambda=10, account_count=100)
    rows_a = MicroFractionWorkloadGenerator(cfg_a).generate()
    rows_b = MicroFractionWorkloadGenerator(cfg_b).generate()
    assert rows_a == rows_b


def test_different_seeds_produce_different_workloads():
    cfg_a = WorkloadConfig(seed=1, epochs=3, poisson_lambda=20, account_count=100)
    cfg_b = WorkloadConfig(seed=2, epochs=3, poisson_lambda=20, account_count=100)
    rows_a = MicroFractionWorkloadGenerator(cfg_a).generate()
    rows_b = MicroFractionWorkloadGenerator(cfg_b).generate()
    assert rows_a != rows_b


def test_account_ids_lie_in_valid_range():
    cfg = WorkloadConfig(seed=7, epochs=3, poisson_lambda=50, account_count=200)
    rows = MicroFractionWorkloadGenerator(cfg).generate()
    assert rows, "workload was empty"
    for r in rows:
        assert 0 <= r["account_id"] < 200


def test_burst_locality_is_observable():
    """With intra_partition_ratio = 1.0 every update should be inside the
    burst anchor's partition."""
    cfg = WorkloadConfig(
        seed=11, epochs=2, poisson_lambda=100, account_count=1000,
        partition_size=100, intra_partition_ratio=1.0,
    )
    rows = MicroFractionWorkloadGenerator(cfg).generate()
    # Group by epoch and confirm each epoch's updates are all in one partition.
    by_epoch = {}
    for r in rows:
        by_epoch.setdefault(r["epoch"], set()).add(r["partition_id"])
    for epoch, parts in by_epoch.items():
        assert len(parts) == 1, f"epoch {epoch} touched {len(parts)} partitions"


def test_delta_magnitudes_are_signed():
    cfg = WorkloadConfig(seed=3, epochs=2, poisson_lambda=200, account_count=200)
    rows = MicroFractionWorkloadGenerator(cfg).generate()
    pos = sum(1 for r in rows if r["delta_units"] > 0)
    neg = sum(1 for r in rows if r["delta_units"] < 0)
    # Random sign on each delta, so both should be present in a large sample.
    assert pos > 0 and neg > 0
