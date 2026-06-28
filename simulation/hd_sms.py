"""Executable HD-SMS prototype.

Architecture (matches the manuscript's three-tier design):
  Tier 0 -- account level: each account is identified by a 64-bit id.
  Tier 1 -- partition level: accounts are bucketed into partitions of
            fixed maximum size; each partition has its own SHA-256
            Sparse Merkle Tree over the local index space.
  Tier 2 -- global level: the global SMT commits to the partition roots.

Leaves bind (account_id, epoch, signed delta, previous balance) so a
proof attests to a state transition rather than to a bare balance.
The previous-balance commitment closes the delta-replay malleability
gap discussed in SECURITY.md.

Two update APIs are exposed:
  - update_delta(account_id, delta, epoch): single-account update.
        Performs both a local-tree update and a global-tree update.
  - update_batch_in_epoch(updates_in_partition, partition_id, epoch):
        applies many account updates within a single partition and
        performs *one* global-tree update at the end. This is where
        HD-SMS realises its theoretical advantage over the per-update
        cost of a single global SMT for clustered workloads.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

from .crypto import HASH_SIZE, hash_delta_leaf, i128
from .smt import SMTProof, SparseMerkleTree


@dataclass(frozen=True)
class HDSMSProof:
    """Two-tier proof: local partition path + global path to root."""
    account_id: int
    partition_id: int
    local_key: int
    epoch: int
    delta_units: int
    previous_balance_units: int
    local_proof: SMTProof
    global_proof: SMTProof

    def byte_size(self) -> int:
        # local + global proof bytes plus 64-byte HD-SMS header
        return self.local_proof.byte_size() + self.global_proof.byte_size() + 64


@dataclass(frozen=True)
class HDSMSBatchProof:
    """Compact batch proof for many accounts within a single partition.

    Local proofs are stored per account; the global proof is shared,
    which is the structural reason HD-SMS verification cost grows more
    slowly than SMT in batch (audit) scenarios.
    """
    partition_id: int
    epoch: int
    local_proofs: Tuple[HDSMSProof, ...]  # share the same global_proof
    shared_global_proof: SMTProof

    def byte_size(self) -> int:
        # Header + shared global proof + per-account (local proof + account fields)
        per_account = sum(p.local_proof.byte_size() + 48 for p in self.local_proofs)
        return 64 + self.shared_global_proof.byte_size() + per_account

    @property
    def account_count(self) -> int:
        return len(self.local_proofs)


class HDSMS:
    """Hierarchical Delta Sparse Merkle Structuring."""

    def __init__(self, account_count: int, partition_size: int = 1024):
        if account_count <= 0:
            raise ValueError("account_count must be positive")
        if partition_size <= 0:
            raise ValueError("partition_size must be positive")
        self.account_count = int(account_count)
        self.partition_size = int(partition_size)
        self.partition_count = math.ceil(self.account_count / self.partition_size)
        self.local_depth = max(1, math.ceil(math.log2(self.partition_size)))
        self.global_depth = max(1, math.ceil(math.log2(self.partition_count)))
        self.partitions: Dict[int, SparseMerkleTree] = {}
        self.global_tree = SparseMerkleTree(self.global_depth)
        self.balances: Dict[int, int] = {}
        self.last_epoch: Dict[int, int] = {}
        self.last_delta: Dict[int, int] = {}

    # ----- internal helpers -----
    @property
    def root(self) -> bytes:
        return self.global_tree.root

    def _partition_id(self, account_id: int) -> int:
        if not 0 <= account_id < self.account_count:
            raise ValueError(f"account {account_id} outside account_count {self.account_count}")
        return account_id // self.partition_size

    def _local_key(self, account_id: int) -> int:
        return account_id % self.partition_size

    def _get_partition(self, partition_id: int) -> SparseMerkleTree:
        if partition_id not in self.partitions:
            self.partitions[partition_id] = SparseMerkleTree(self.local_depth)
        return self.partitions[partition_id]

    def _apply_one_local(self, account_id: int, delta_units: int, epoch: int,
                         local_tree: SparseMerkleTree) -> int:
        """Apply a single account update inside its local partition tree.

        Returns the number of SHA-256 operations performed on the local
        tree only. Does NOT touch the global tree -- the caller is
        responsible for that, so batch callers can defer it.
        """
        previous = self.balances.get(account_id, 0)
        new_balance = previous + int(delta_units)
        if new_balance < 0:
            # Reject debit that would drive balance negative; record as no-op.
            delta_units = 0
            new_balance = previous
        local_key = self._local_key(account_id)
        leaf_commitment = hash_delta_leaf(account_id, epoch, int(delta_units), previous)
        value = leaf_commitment + i128(new_balance)
        local_ops = local_tree.update(local_key, value)
        self.balances[account_id] = new_balance
        self.last_epoch[account_id] = epoch
        self.last_delta[account_id] = int(delta_units)
        return local_ops

    # ----- public API: single-account -----
    def update_delta(self, account_id: int, delta_units: int, epoch: int) -> int:
        """Apply a single signed delta. Returns total SHA-256 operations
        (local-tree update + global-tree update)."""
        partition_id = self._partition_id(account_id)
        local_tree = self._get_partition(partition_id)
        local_ops = self._apply_one_local(account_id, delta_units, epoch, local_tree)
        global_ops = self.global_tree.update(partition_id, local_tree.root)
        return local_ops + global_ops

    def prove(self, account_id: int) -> HDSMSProof:
        """Build a single-account proof against the current global root."""
        partition_id = self._partition_id(account_id)
        local_key = self._local_key(account_id)
        local_tree = self._get_partition(partition_id)
        current_balance = self.balances.get(account_id, 0)
        delta = self.last_delta.get(account_id, 0)
        epoch = self.last_epoch.get(account_id, 0)
        previous = current_balance - delta
        return HDSMSProof(
            account_id=account_id,
            partition_id=partition_id,
            local_key=local_key,
            epoch=epoch,
            delta_units=delta,
            previous_balance_units=previous,
            local_proof=local_tree.prove(local_key),
            global_proof=self.global_tree.prove(partition_id),
        )

    @staticmethod
    def verify(root: bytes, proof: HDSMSProof) -> bool:
        """Verify a single HD-SMS proof against the published global root."""
        leaf_commitment = hash_delta_leaf(
            proof.account_id,
            proof.epoch,
            proof.delta_units,
            proof.previous_balance_units,
        )
        new_balance = proof.previous_balance_units + proof.delta_units
        expected_local_value = leaf_commitment + i128(new_balance)
        if proof.local_proof.value != expected_local_value:
            return False
        local_ok = SparseMerkleTree.verify(proof.global_proof.value, proof.local_proof)
        if not local_ok:
            return False
        return SparseMerkleTree.verify(root, proof.global_proof)

    # ----- public API: batch within a single partition -----
    def update_batch_in_epoch(self,
                              updates: Iterable[Tuple[int, int]],
                              epoch: int) -> Dict[str, int]:
        """Apply multiple (account_id, delta) updates in one epoch.

        Updates are grouped by partition; for each affected partition the
        global tree is updated *once* with the partition's final root.
        This is the path-sharing optimisation that makes HD-SMS
        algorithmically attractive for clustered workloads.

        Returns a small accounting dict so the caller can see how much
        work was done locally vs globally.
        """
        updates_by_partition: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        for account_id, delta in updates:
            updates_by_partition[self._partition_id(account_id)].append(
                (int(account_id), int(delta))
            )
        local_ops = 0
        global_ops = 0
        touched_partitions = 0
        touched_accounts = 0
        for partition_id, partition_updates in updates_by_partition.items():
            local_tree = self._get_partition(partition_id)
            for account_id, delta in partition_updates:
                local_ops += self._apply_one_local(account_id, delta, epoch, local_tree)
                touched_accounts += 1
            global_ops += self.global_tree.update(partition_id, local_tree.root)
            touched_partitions += 1
        return {
            "local_hash_ops": local_ops,
            "global_hash_ops": global_ops,
            "total_hash_ops": local_ops + global_ops,
            "touched_partitions": touched_partitions,
            "touched_accounts": touched_accounts,
        }

    def prove_batch(self, account_ids: Iterable[int]) -> List[HDSMSBatchProof]:
        """Build one HDSMSBatchProof per (epoch, partition) group present in
        the input. Accounts within a group share the global proof.
        """
        # Group by (epoch, partition)
        grouped: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for account_id in account_ids:
            partition_id = self._partition_id(account_id)
            epoch = self.last_epoch.get(account_id, 0)
            grouped[(partition_id, epoch)].append(account_id)
        result: List[HDSMSBatchProof] = []
        for (partition_id, epoch), accounts in grouped.items():
            local_proofs = [self.prove(a) for a in accounts]
            # All accounts in this group share an identical global proof at the
            # current root; take the first one as the canonical shared proof.
            shared_global = local_proofs[0].global_proof
            result.append(
                HDSMSBatchProof(
                    partition_id=partition_id,
                    epoch=epoch,
                    local_proofs=tuple(local_proofs),
                    shared_global_proof=shared_global,
                )
            )
        return result

    @staticmethod
    def verify_batch(root: bytes, batch_proof: HDSMSBatchProof) -> bool:
        """Verify a batch of intra-partition proofs against the global root.

        The global proof is verified once for the whole batch; each local
        proof is verified individually against the partition root encoded
        in the shared global proof's value field.
        """
        # 1) global proof binds partition_id -> partition_root
        if not SparseMerkleTree.verify(root, batch_proof.shared_global_proof):
            return False
        partition_root = batch_proof.shared_global_proof.value
        # 2) each local proof verifies against that partition_root
        for proof in batch_proof.local_proofs:
            leaf_commitment = hash_delta_leaf(
                proof.account_id,
                proof.epoch,
                proof.delta_units,
                proof.previous_balance_units,
            )
            new_balance = proof.previous_balance_units + proof.delta_units
            expected_local_value = leaf_commitment + i128(new_balance)
            if proof.local_proof.value != expected_local_value:
                return False
            if not SparseMerkleTree.verify(partition_root, proof.local_proof):
                return False
        return True

    # ----- storage accounting -----
    def storage_bytes(self) -> int:
        """Total in-memory storage: global tree + all partition trees + balance map."""
        global_bytes = self.global_tree.storage_bytes()
        partition_bytes = sum(t.storage_bytes() for t in self.partitions.values())
        # 8 bytes account_id key + 16 bytes balance value per balance entry
        balance_bytes = len(self.balances) * 24
        return global_bytes + partition_bytes + balance_bytes
