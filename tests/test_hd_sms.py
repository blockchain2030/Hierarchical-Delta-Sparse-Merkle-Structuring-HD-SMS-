"""Unit tests for the HD-SMS hierarchical delta tree."""
from dataclasses import replace

import pytest

from simulation.hd_sms import HDSMS, HDSMSProof
from simulation.smt import SparseMerkleTree


def test_constructor_rejects_invalid_arguments():
    with pytest.raises(ValueError):
        HDSMS(account_count=0)
    with pytest.raises(ValueError):
        HDSMS(account_count=10, partition_size=0)


def test_proof_verifies_after_single_delta_update():
    hd = HDSMS(account_count=1000, partition_size=100)
    hd.update_delta(account_id=123, delta_units=50, epoch=1)
    proof = hd.prove(123)
    assert HDSMS.verify(hd.root, proof)


def test_proof_verifies_after_many_updates_across_partitions():
    hd = HDSMS(account_count=10_000, partition_size=100)
    for i in range(50):
        account_id = (i * 137) % 10_000
        hd.update_delta(account_id=account_id, delta_units=10 * (i + 1), epoch=i // 10)
    for i in range(50):
        account_id = (i * 137) % 10_000
        proof = hd.prove(account_id)
        assert HDSMS.verify(hd.root, proof), f"proof failed for account {account_id}"


def test_balance_evolves_under_multiple_deltas():
    hd = HDSMS(account_count=100, partition_size=10)
    hd.update_delta(account_id=5, delta_units=100, epoch=1)
    hd.update_delta(account_id=5, delta_units=-30, epoch=2)
    hd.update_delta(account_id=5, delta_units=10, epoch=3)
    assert hd.balances[5] == 80
    proof = hd.prove(5)
    assert HDSMS.verify(hd.root, proof)


def test_overdraw_is_clamped_to_zero_delta():
    """A debit larger than the current balance is silently rejected
    (recorded as a zero-delta no-op) so the integer balance never goes
    negative."""
    hd = HDSMS(account_count=100, partition_size=10)
    hd.update_delta(account_id=5, delta_units=50, epoch=1)
    hd.update_delta(account_id=5, delta_units=-1000, epoch=2)   # over-debit
    assert hd.balances[5] == 50


def test_tampered_local_value_rejected():
    hd = HDSMS(account_count=100, partition_size=10)
    hd.update_delta(account_id=5, delta_units=50, epoch=1)
    proof = hd.prove(5)
    fake_local = replace(proof.local_proof, value=b"\x00" * len(proof.local_proof.value))
    fake = replace(proof, local_proof=fake_local)
    assert not HDSMS.verify(hd.root, fake)


def test_tampered_delta_rejected():
    hd = HDSMS(account_count=100, partition_size=10)
    hd.update_delta(account_id=5, delta_units=50, epoch=1)
    proof = hd.prove(5)
    fake = replace(proof, delta_units=999_999)
    assert not HDSMS.verify(hd.root, fake)


def test_tampered_previous_balance_rejected():
    hd = HDSMS(account_count=100, partition_size=10)
    hd.update_delta(account_id=5, delta_units=50, epoch=1)
    hd.update_delta(account_id=5, delta_units=20, epoch=2)
    proof = hd.prove(5)
    fake = replace(proof, previous_balance_units=999)
    assert not HDSMS.verify(hd.root, fake)


def test_proof_against_wrong_root_rejected():
    hd1 = HDSMS(account_count=100, partition_size=10)
    hd2 = HDSMS(account_count=100, partition_size=10)
    hd1.update_delta(account_id=5, delta_units=50, epoch=1)
    hd2.update_delta(account_id=5, delta_units=51, epoch=1)
    proof = hd1.prove(5)
    assert HDSMS.verify(hd1.root, proof)
    assert not HDSMS.verify(hd2.root, proof)


def test_batch_update_yields_same_state_as_sequential():
    """For the same set of updates in the same order, batch and sequential
    update paths must end with identical roots."""
    updates = [(7, 100), (7, 50), (42, 30), (42, -10), (199, 5)]
    epoch = 1

    hd_batch = HDSMS(account_count=1000, partition_size=100)
    hd_seq = HDSMS(account_count=1000, partition_size=100)

    hd_batch.update_batch_in_epoch(updates, epoch=epoch)
    for account_id, delta in updates:
        hd_seq.update_delta(account_id, delta, epoch=epoch)

    assert hd_batch.root == hd_seq.root
    for account_id in {a for a, _ in updates}:
        assert hd_batch.balances[account_id] == hd_seq.balances[account_id]


def test_batch_update_amortises_global_tree_work():
    """If many updates land in one partition the batch path must do
    strictly fewer global-tree hashes than the sequential path."""
    n = 1000
    p = 100
    same_partition_updates = [(i, 10) for i in range(50)]   # all in partition 0
    epoch = 1

    hd_seq = HDSMS(account_count=n, partition_size=p)
    seq_total = sum(hd_seq.update_delta(a, d, epoch) for a, d in same_partition_updates)

    hd_batch = HDSMS(account_count=n, partition_size=p)
    report = hd_batch.update_batch_in_epoch(same_partition_updates, epoch=epoch)

    assert hd_batch.root == hd_seq.root
    assert report["total_hash_ops"] < seq_total, (
        f"batch should amortise global tree: got {report['total_hash_ops']} vs {seq_total}"
    )


def test_batch_verify_passes_for_correct_proofs():
    hd = HDSMS(account_count=1000, partition_size=100)
    same_partition_accounts = [0, 1, 2, 3, 4, 5]
    for a in same_partition_accounts:
        hd.update_delta(a, 10 * (a + 1), epoch=1)
    batches = hd.prove_batch(same_partition_accounts)
    assert len(batches) == 1
    assert HDSMS.verify_batch(hd.root, batches[0])


def test_batch_verify_rejects_tampered_local_proof():
    hd = HDSMS(account_count=1000, partition_size=100)
    for a in [0, 1, 2]:
        hd.update_delta(a, 10, epoch=1)
    batches = hd.prove_batch([0, 1, 2])
    bad_local = list(batches[0].local_proofs)
    # Tamper with one local proof's delta field
    bad_local[1] = replace(bad_local[1], delta_units=99999)
    bad_batch = replace(batches[0], local_proofs=tuple(bad_local))
    assert not HDSMS.verify_batch(hd.root, bad_batch)


def test_batch_proof_byte_size_grows_sublinearly_in_batch():
    """One shared global proof: bytes per account decreases as batch grows."""
    hd = HDSMS(account_count=10_000, partition_size=1_000)
    # Populate 100 accounts in partition 0
    for i in range(100):
        hd.update_delta(i, 10 * (i + 1), epoch=1)
    # Per-account byte size for batch of 10 vs batch of 100
    batches_10 = hd.prove_batch(list(range(10)))
    batches_100 = hd.prove_batch(list(range(100)))
    per_acct_10 = batches_10[0].byte_size() / 10
    per_acct_100 = batches_100[0].byte_size() / 100
    assert per_acct_100 < per_acct_10, (
        f"per-account bytes should decrease with batch size: {per_acct_10} -> {per_acct_100}"
    )


def test_out_of_range_account_rejected():
    hd = HDSMS(account_count=100, partition_size=10)
    with pytest.raises(ValueError):
        hd.update_delta(account_id=100, delta_units=1, epoch=0)
    with pytest.raises(ValueError):
        hd.update_delta(account_id=-1, delta_units=1, epoch=0)
