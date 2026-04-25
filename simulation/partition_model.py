"""
partition_model.py

Partitioning and sparse-state model for HD-SMS experiments.

This module provides:
- deterministic account-to-partition assignment
- partition-level active account tracking
- sparse branch activity estimation
- localized recomputation-cost estimation

It is designed to support experiments comparing HD-SMS with baseline
authenticated data structures such as Sparse Merkle Trees and Verkle Trees.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set


@dataclass
class PartitionConfig:
    account_count: int = 10_000
    partition_count: int = 100
    max_partition_size: int = 1_000
    branching_factor: int = 16


class PartitionModel:
    def __init__(self, config: PartitionConfig):
        self.config = config
        self.account_to_partition = self._build_partition_map()

    def _build_partition_map(self) -> Dict[int, int]:
        mapping: Dict[int, int] = {}
        for account_id in range(self.config.account_count):
            partition_id = min(
                account_id // self.config.max_partition_size,
                self.config.partition_count - 1,
            )
            mapping[account_id] = partition_id
        return mapping

    def partition_of(self, account_id: int) -> int:
        return self.account_to_partition[int(account_id)]

    def local_tree_height(self) -> int:
        return math.ceil(
            math.log(max(self.config.max_partition_size, 1), self.config.branching_factor)
        )

    def global_partition_height(self) -> int:
        return math.ceil(
            math.log(max(self.config.partition_count, 1), self.config.branching_factor)
        )

    def baseline_global_height(self) -> int:
        return math.ceil(
            math.log(max(self.config.account_count, 1), self.config.branching_factor)
        )

    def estimate_hd_sms_update_cost(self, active_accounts_in_partition: int) -> int:
        """
        Estimate localized HD-SMS recomputation cost.

        Cost is bounded by local partition height plus global partition height,
        but reduced when few accounts are active due to sparse branch caching.
        """
        local_height = self.local_tree_height()
        global_height = self.global_partition_height()

        if active_accounts_in_partition <= 0:
            return 1

        sparse_factor = min(
            1.0,
            math.log(active_accounts_in_partition + 1, self.config.branching_factor)
            / max(local_height, 1),
        )

        localized_cost = math.ceil(local_height * sparse_factor) + global_height
        return max(1, localized_cost)

    def estimate_smt_update_cost(self) -> int:
        return self.baseline_global_height()

    def estimate_verkle_update_cost(self) -> int:
        return self.baseline_global_height() + 1

    def summarize_epoch(self, rows: Iterable[Dict[str, str]]) -> Dict[str, object]:
        active_by_partition: Dict[int, Set[int]] = defaultdict(set)

        for row in rows:
            account_id = int(row["account_id"])
            partition_id = int(row.get("partition_id", self.partition_of(account_id)))
            active_by_partition[partition_id].add(account_id)

        active_partitions = len(active_by_partition)
        active_accounts = sum(len(v) for v in active_by_partition.values())

        if active_partitions == 0:
            avg_hd_cost = 1.0
        else:
            costs = [
                self.estimate_hd_sms_update_cost(len(accounts))
                for accounts in active_by_partition.values()
            ]
            avg_hd_cost = sum(costs) / len(costs)

        return {
            "active_partitions": active_partitions,
            "active_accounts": active_accounts,
            "avg_hd_sms_update_cost": round(avg_hd_cost, 4),
            "smt_update_cost": self.estimate_smt_update_cost(),
            "verkle_update_cost": self.estimate_verkle_update_cost(),
            "sparse_activity_ratio": round(
                active_accounts / max(self.config.account_count, 1), 8
            ),
        }


def read_workload_by_epoch(path: Path) -> Dict[int, List[Dict[str, str]]]:
    epochs: Dict[int, List[Dict[str, str]]] = defaultdict(list)

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            epochs[int(row["epoch"])].append(row)

    return epochs


def write_partition_summary(
    workload_path: Path,
    output_path: Path,
    config: PartitionConfig,
) -> None:
    model = PartitionModel(config)
    epochs = read_workload_by_epoch(workload_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "epoch",
        "active_partitions",
        "active_accounts",
        "avg_hd_sms_update_cost",
        "smt_update_cost",
        "verkle_update_cost",
        "sparse_activity_ratio",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for epoch in sorted(epochs):
            summary = model.summarize_epoch(epochs[epoch])
            summary["epoch"] = epoch
            writer.writerow(summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate partition activity and localized update costs for HD-SMS."
    )

    parser.add_argument("--workload", type=str, default="data/generated_workloads.csv")
    parser.add_argument("--output", type=str, default="results/partition_summary.csv")
    parser.add_argument("--account-count", type=int, default=10_000)
    parser.add_argument("--partition-count", type=int, default=100)
    parser.add_argument("--max-partition-size", type=int, default=1_000)
    parser.add_argument("--branching-factor", type=int, default=16)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = PartitionConfig(
        account_count=args.account_count,
        partition_count=args.partition_count,
        max_partition_size=args.max_partition_size,
        branching_factor=args.branching_factor,
    )

    write_partition_summary(
        workload_path=Path(args.workload),
        output_path=Path(args.output),
        config=config,
    )

    print(f"Partition summary written to: {args.output}")


if __name__ == "__main__":
    main()
