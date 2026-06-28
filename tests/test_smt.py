"""Unit tests for the Sparse Merkle Tree baseline."""
from dataclasses import replace

import pytest

from simulation.crypto import i128
from simulation.smt import SMTProof, SparseMerkleTree


def test_constructor_rejects_non_positive_depth():
    with pytest.raises(ValueError):
        SparseMerkleTree(depth=0)
    with pytest.raises(ValueError):
        SparseMerkleTree(depth=-1)


def test_empty_tree_root_is_default_hash():
    t = SparseMerkleTree(depth=8)
    assert t.root == t.default_hashes[t.depth]


def test_proof_verifies_after_update():
    t = SparseMerkleTree(depth=8)
    t.update(7, i128(123))
    proof = t.prove(7)
    assert SparseMerkleTree.verify(t.root, proof)


def test_proof_verifies_after_many_updates():
    t = SparseMerkleTree(depth=10)
    for i in range(20):
        t.update(i * 7 % (2 ** 10), i128(i * 100))
    for i in range(20):
        proof = t.prove(i * 7 % (2 ** 10))
        assert SparseMerkleTree.verify(t.root, proof)


def test_update_returns_positive_hash_count():
    t = SparseMerkleTree(depth=8)
    ops = t.update(5, i128(42))
    assert ops > 0  # one leaf hash + at least one path node


def test_repeated_update_to_same_key_overwrites():
    t = SparseMerkleTree(depth=8)
    t.update(5, i128(1))
    root_1 = t.root
    t.update(5, i128(2))
    root_2 = t.root
    assert root_1 != root_2
    proof = t.prove(5)
    assert proof.value == i128(2)
    assert SparseMerkleTree.verify(t.root, proof)


def test_out_of_range_key_rejected():
    t = SparseMerkleTree(depth=4)
    with pytest.raises(ValueError):
        t.update(16, i128(1))    # 16 == 2**depth
    with pytest.raises(ValueError):
        t.prove(-1)


def test_tampered_value_rejected():
    t = SparseMerkleTree(depth=8)
    t.update(7, i128(100))
    proof = t.prove(7)
    fake = replace(proof, value=i128(999))
    assert not SparseMerkleTree.verify(t.root, fake)


def test_tampered_sibling_rejected():
    t = SparseMerkleTree(depth=8)
    t.update(7, i128(100))
    t.update(8, i128(200))
    proof = t.prove(7)
    # Flip one bit in the first sibling.
    bad_siblings = list(proof.siblings)
    bad_siblings[0] = bytes(b ^ 0x01 for b in bad_siblings[0])
    fake = replace(proof, siblings=tuple(bad_siblings))
    assert not SparseMerkleTree.verify(t.root, fake)


def test_proof_against_wrong_root_rejected():
    t1 = SparseMerkleTree(depth=8)
    t2 = SparseMerkleTree(depth=8)
    t1.update(3, i128(1))
    t2.update(3, i128(2))
    proof = t1.prove(3)
    assert SparseMerkleTree.verify(t1.root, proof)
    assert not SparseMerkleTree.verify(t2.root, proof)


def test_batch_verify_passes_for_all_correct_proofs():
    t = SparseMerkleTree(depth=10)
    keys = list(range(0, 100, 7))
    for k in keys:
        t.update(k, i128(k * 10))
    proofs = [t.prove(k) for k in keys]
    assert SparseMerkleTree.verify_batch(t.root, proofs)


def test_storage_grows_with_distinct_updates():
    t = SparseMerkleTree(depth=10)
    s0 = t.storage_bytes()
    t.update(0, i128(1))
    s1 = t.storage_bytes()
    t.update(500, i128(2))
    s2 = t.storage_bytes()
    assert s0 < s1 < s2


def test_hash_ops_counter_monotone_nondecreasing():
    t = SparseMerkleTree(depth=8)
    before = t.hash_ops
    t.update(1, i128(1))
    after = t.hash_ops
    assert after > before


def test_proof_byte_size_matches_serialised_layout():
    t = SparseMerkleTree(depth=8)
    t.update(3, i128(1))
    p = t.prove(3)
    expected = len(p.value) + len(p.siblings) * 32 + 16
    assert p.byte_size() == expected
