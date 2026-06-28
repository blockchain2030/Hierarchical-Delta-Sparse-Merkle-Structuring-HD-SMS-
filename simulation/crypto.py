"""Cryptographic helpers for HD-SMS experiments.

All hashes use SHA-256 with domain separation. This file is intentionally
small and dependency-free so reviewers can audit the commitment logic.

Domain-separation tags include a version suffix (v1) so future revisions
do not silently collide with the current commitment scheme.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Iterable

HASH_SIZE = 32                       # SHA-256 digest in bytes
ZERO_HASH = b"\x00" * HASH_SIZE      # canonical empty-leaf placeholder

# Domain separation tags (versioned to allow future scheme changes).
DOMAIN_LEAF = b"HD-SMS:LEAF:v1"
DOMAIN_NODE = b"HD-SMS:NODE:v1"
DOMAIN_DELTA_LEAF = b"HD-SMS:DELTA-LEAF:v1"


def u64(value: int) -> bytes:
    """Encode a non-negative integer as big-endian 8 bytes."""
    if value < 0:
        raise ValueError("u64 cannot encode a negative value")
    return struct.pack(">Q", int(value))


def i128(value: int) -> bytes:
    """Encode a signed integer as big-endian 16 bytes (supports negative balances)."""
    return int(value).to_bytes(16, "big", signed=True)


def sha256_parts(domain: bytes, parts: Iterable[bytes]) -> bytes:
    """Compute SHA-256 over a domain tag and a sequence of length-prefixed parts.

    Length-prefixing prevents ambiguous concatenation: H("ab", "c") never
    collides with H("a", "bc").
    """
    h = hashlib.sha256()
    h.update(domain)
    for part in parts:
        h.update(len(part).to_bytes(4, "big"))
        h.update(part)
    return h.digest()


def hash_leaf(key: int, value: bytes) -> bytes:
    """Hash a generic SMT leaf binding (key, value)."""
    return sha256_parts(DOMAIN_LEAF, [u64(key), value])


def hash_node(left: bytes, right: bytes) -> bytes:
    """Hash an internal Merkle node from its two children."""
    return sha256_parts(DOMAIN_NODE, [left, right])


def hash_delta_leaf(account_id: int, epoch: int, delta_units: int,
                    previous_balance_units: int) -> bytes:
    """Hash an HD-SMS delta-encoded leaf.

    The leaf binds the account identifier, the epoch, the signed delta,
    and the previous balance. Binding the previous balance prevents replay
    of a delta against a different prior state.
    """
    return sha256_parts(
        DOMAIN_DELTA_LEAF,
        [u64(account_id), u64(epoch), i128(delta_units), i128(previous_balance_units)],
    )


def hex_hash(value: bytes) -> str:
    """Convenience helper for debug output."""
    return value.hex()
