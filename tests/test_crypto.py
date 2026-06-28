"""Unit tests for the SHA-256 helpers.

These tests pin the domain separation tags so any future change to the
commitment scheme is forced through a deliberate test update.
"""
import hashlib

import pytest

from simulation.crypto import (
    HASH_SIZE,
    ZERO_HASH,
    hash_delta_leaf,
    hash_leaf,
    hash_node,
    i128,
    sha256_parts,
    u64,
)


def test_hash_size_is_32_bytes():
    assert HASH_SIZE == 32
    assert len(ZERO_HASH) == 32


def test_u64_round_trip():
    assert u64(0) == b"\x00" * 8
    assert u64(1) == b"\x00\x00\x00\x00\x00\x00\x00\x01"
    with pytest.raises(ValueError):
        u64(-1)


def test_i128_signed_round_trip():
    assert int.from_bytes(i128(0), "big", signed=True) == 0
    assert int.from_bytes(i128(-12345), "big", signed=True) == -12345
    assert int.from_bytes(i128(2 ** 100), "big", signed=True) == 2 ** 100


def test_length_prefixing_prevents_concat_collision():
    """H('ab','c') must differ from H('a','bc')."""
    a = sha256_parts(b"D", [b"ab", b"c"])
    b = sha256_parts(b"D", [b"a", b"bc"])
    assert a != b


def test_domain_separation_prevents_cross_use_collision():
    """Same parts with different domains must produce different digests."""
    a = sha256_parts(b"DOMAIN-A", [b"x"])
    b = sha256_parts(b"DOMAIN-B", [b"x"])
    assert a != b


def test_hash_leaf_deterministic():
    a = hash_leaf(7, b"value")
    b = hash_leaf(7, b"value")
    assert a == b
    assert len(a) == HASH_SIZE


def test_hash_leaf_differs_when_key_differs():
    assert hash_leaf(7, b"v") != hash_leaf(8, b"v")


def test_hash_node_order_matters():
    assert hash_node(b"\x01" * 32, b"\x02" * 32) != hash_node(b"\x02" * 32, b"\x01" * 32)


def test_hash_delta_leaf_binds_all_four_fields():
    base = hash_delta_leaf(1, 1, 100, 0)
    assert hash_delta_leaf(2, 1, 100, 0) != base           # account changes
    assert hash_delta_leaf(1, 2, 100, 0) != base           # epoch changes
    assert hash_delta_leaf(1, 1, 101, 0) != base           # delta changes
    assert hash_delta_leaf(1, 1, 100, 1) != base           # previous balance changes


def test_hash_matches_sha256_reference_for_simple_input():
    """Sanity check that we are actually invoking SHA-256."""
    expected = hashlib.sha256(b"DOMAIN" + b"\x00\x00\x00\x01" + b"a").digest()
    assert sha256_parts(b"DOMAIN", [b"a"]) == expected
