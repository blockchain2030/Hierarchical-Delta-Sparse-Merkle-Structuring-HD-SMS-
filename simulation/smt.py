"""Executable Sparse Merkle Tree baseline.

This is not an estimator: every update performs real SHA-256 hashing,
stores only non-default nodes, generates proofs whose sibling hashes
match the current tree state, and verifies those proofs against the
published root.

The tree is the standard SMT baseline used by the manuscript for
comparison against HD-SMS. The reference implementation follows the
construction by Dahlberg, Pulls and Peeters (2016) "Efficient Sparse
Merkle Trees" with the optimisations:
  - default-hash table for empty subtrees of every depth
  - sparse node dictionary (only non-default nodes are stored)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from .crypto import HASH_SIZE, ZERO_HASH, hash_leaf, hash_node


@dataclass(frozen=True)
class SMTProof:
    """Membership proof for a single key in a Sparse Merkle Tree."""
    key: int
    value: bytes
    siblings: Tuple[bytes, ...]
    depth: int

    def byte_size(self) -> int:
        """Serialised proof size: value + (depth) sibling hashes + small header."""
        return len(self.value) + len(self.siblings) * HASH_SIZE + 16


class SparseMerkleTree:
    """SHA-256-based Sparse Merkle Tree over a fixed-depth key space."""

    def __init__(self, depth: int):
        if depth <= 0:
            raise ValueError("depth must be positive")
        self.depth = int(depth)
        self.nodes: Dict[Tuple[int, int], bytes] = {}
        self.values: Dict[int, bytes] = {}
        self.default_hashes = self._build_default_hashes()
        self.hash_ops = 0

    # ----- internal helpers -----
    def _build_default_hashes(self) -> List[bytes]:
        """default_hashes[ell] is the SHA-256 root of an all-zero subtree of depth ell."""
        defaults = [ZERO_HASH]
        for _ in range(self.depth):
            defaults.append(hash_node(defaults[-1], defaults[-1]))
        return defaults

    def _get_node(self, level: int, index: int) -> bytes:
        return self.nodes.get((level, index), self.default_hashes[level])

    # ----- public API -----
    @property
    def root(self) -> bytes:
        """Current Merkle root (top-level commitment)."""
        return self.nodes.get((self.depth, 0), self.default_hashes[self.depth])

    def update(self, key: int, value: bytes) -> int:
        """Set the value at `key`. Returns the number of SHA-256 invocations."""
        if not 0 <= key < 2 ** self.depth:
            raise ValueError(f"key {key} outside tree depth {self.depth}")
        before = self.hash_ops
        leaf_hash = hash_leaf(key, value)
        self.hash_ops += 1
        self.values[key] = value
        self.nodes[(0, key)] = leaf_hash
        idx = key
        child_hash = leaf_hash
        for level in range(1, self.depth + 1):
            sibling_idx = idx ^ 1
            sibling_hash = self._get_node(level - 1, sibling_idx)
            if idx % 2 == 0:
                parent_hash = hash_node(child_hash, sibling_hash)
            else:
                parent_hash = hash_node(sibling_hash, child_hash)
            self.hash_ops += 1
            idx //= 2
            child_hash = parent_hash
            if parent_hash == self.default_hashes[level]:
                self.nodes.pop((level, idx), None)
            else:
                self.nodes[(level, idx)] = parent_hash
        return self.hash_ops - before

    def update_batch(self, updates: Iterable[Tuple[int, bytes]]) -> int:
        """Convenience batch wrapper. SMT has no path-sharing across distinct keys,
        so this is mathematically equivalent to sequential update() calls; it
        exists solely so the benchmark can call SMT and HD-SMS through a
        symmetric API.
        """
        before = self.hash_ops
        for key, value in updates:
            self.update(key, value)
        return self.hash_ops - before

    def prove(self, key: int) -> SMTProof:
        """Build a membership proof for `key` against the current root."""
        if not 0 <= key < 2 ** self.depth:
            raise ValueError(f"key {key} outside tree depth {self.depth}")
        siblings: List[bytes] = []
        idx = key
        for level in range(self.depth):
            siblings.append(self._get_node(level, idx ^ 1))
            idx //= 2
        return SMTProof(
            key=key,
            value=self.values.get(key, b""),
            siblings=tuple(siblings),
            depth=self.depth,
        )

    @staticmethod
    def verify(root: bytes, proof: SMTProof) -> bool:
        """Reconstruct the root from the proof and compare to the published root."""
        current = hash_leaf(proof.key, proof.value)
        idx = proof.key
        for sibling in proof.siblings:
            if idx % 2 == 0:
                current = hash_node(current, sibling)
            else:
                current = hash_node(sibling, current)
            idx //= 2
        return current == root

    @staticmethod
    def verify_batch(root: bytes, proofs: Iterable[SMTProof]) -> bool:
        """Verify a sequence of independent SMT proofs against the same root.

        SMT has no shared structure across distinct keys, so this is the
        cost-honest baseline against which HD-SMS batch verification is
        compared (HD-SMS *does* have shared structure across keys in the
        same partition).
        """
        return all(SparseMerkleTree.verify(root, p) for p in proofs)

    def storage_bytes(self) -> int:
        """In-memory storage for the sparse node set and the stored values."""
        return len(self.nodes) * HASH_SIZE + sum(len(v) for v in self.values.values())
