"""
workload_generator.py

Workload generator for Hierarchical Delta Sparse Merkle Structuring (HD-SMS)
experiments.

This script creates high-frequency micro-fraction token transfer workloads using:
- Poisson distribution for updates per epoch
- Zipfian distribution for account selection
- Log-normal distribution for micro-fraction delta magnitude
- Intra-partition burst locality

The generated output can be used for update-cost, proof-size, storage, and
verification-latency experiments.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np


@dataclass
class WorkloadConfig:
    account_count: int = 10_000
    partition_count: int = 100
    max_partition_size: int = 1_000
    epochs: int = 10_000
    poisson_lambda: int = 500
    zipf_alpha: float = 1.2
    lognormal_mu: float = -12.0
    lognormal_sigma: float = 2.0
    intra_partition_ratio: float = 0.70
    total_supply: float = 1_000_000.0
    seed: int = 42


class MicroFractionWorkloadGenerator:
    def __init__(self, config: WorkloadConfig):
        self.config = config
        random.seed(config.seed)
        np.random.seed(config.seed)

        self.accounts = np.arange(config.account_count)
        self.account_to_partition = self._assign_partitions()

    def _assign_partitions(self) -> Dict[int, int]:
        mapping = {}
        for account_id in range(self.config.account_count):
            partition_id = min(
                account_id // self.config.max_partition_size,
                self.config.partition_count - 1,
            )
            mapping[account_id] = partition_id
        return mapping

    def _sample_account_zipf(self) -> int:
        while True:
            sampled = np.random.zipf(self.config.zipf_alpha) - 1
            if 0 <= sampled < self.config.account_count:
                return int(sampled)

    def _sample_account_from_partition(self, partition_id: int) -> int:
        start = partition_id * self.config.max_partition_size
        end = min(start + self.config.max_partition_size, self.config.account_count)
        if start >= end:
            return self._sample_account_zipf()
        return random.randint(start, end - 1)

    def _sample_delta(self) -> float:
        raw = np.random.lognormal(
            mean=self.config.lognormal_mu,
            sigma=self.config.lognormal_sigma,
        )
        return float(raw * self.config.total_supply)

    def generate_epoch(self, epoch: int) -> List[Dict[str, object]]:
        update_count = int(np.random.poisson(self.config.poisson_lambda))
        rows: List[Dict[str, object]] = []

        anchor_account = self._sample_account_zipf()
        anchor_partition = self.account_to_partition[anchor_account]

        for update_index in range(update_count):
            use_local_partition = random.random() < self.config.intra_partition_ratio

            if use_local_partition:
                account_id = self._sample_account_from_partition(anchor_partition)
            else:
                account_id = self._sample_account_zipf()

            partition_id = self.account_to_partition[account_id]
            delta = self._sample_delta()

            # Randomly simulate credit/debit behavior.
            if random.random() < 0.5:
                delta = -delta

            rows.append(
                {
                    "epoch": epoch,
                    "update_index": update_index,
                    "account_id": account_id,
                    "partition_id": partition_id,
                    "delta": delta,
                    "abs_delta": abs(delta),
                    "delta_ratio_of_supply": abs(delta) / self.config.total_supply,
                    "is_intra_partition_burst": int(use_local_partition),
                }
            )

        return rows

    def generate(self) -> List[Dict[str, object]]:
        all_rows: List[Dict[str, object]] = []
        for epoch in range(self.config.epochs):
            all_rows.extend(self.generate_epoch(epoch))
        return all_rows

    def write_csv(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.generate()

        fieldnames = [
            "epoch",
            "update_index",
            "account_id",
            "partition_id",
            "delta",
            "abs_delta",
            "delta_ratio_of_supply",
            "is_intra_partition_burst",
        ]

        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate micro-fraction token transfer workloads for HD-SMS experiments."
    )

    parser.add_argument("--account-count", type=int, default=10_000)
    parser.add_argument("--partition-count", type=int, default=100)
    parser.add_argument("--max-partition-size", type=int, default=1_000)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--lambda-updates", type=int, default=500)
    parser.add_argument("--zipf-alpha", type=float, default=1.2)
    parser.add_argument("--lognormal-mu", type=float, default=-12.0)
    parser.add_argument("--lognormal-sigma", type=float, default=2.0)
    parser.add_argument("--intra-partition-ratio", type=float, default=0.70)
    parser.add_argument("--total-supply", type=float, default=1_000_000.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--output",
        type=str,
        default="data/generated_workloads.csv",
        help="Output CSV path.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = WorkloadConfig(
        account_count=args.account_count,
        partition_count=args.partition_count,
        max_partition_size=args.max_partition_size,
        epochs=args.epochs,
        poisson_lambda=args.lambda_updates,
        zipf_alpha=args.zipf_alpha,
        lognormal_mu=args.lognormal_mu,
        lognormal_sigma=args.lognormal_sigma,
        intra_partition_ratio=args.intra_partition_ratio,
        total_supply=args.total_supply,
        seed=args.seed,
    )

    generator = MicroFractionWorkloadGenerator(config)
    generator.write_csv(Path(args.output))

    print(f"Workload generated successfully: {args.output}")
    print(f"Accounts: {config.account_count}")
    print(f"Partitions: {config.partition_count}")
    print(f"Epochs: {config.epochs}")
    print(f"Expected updates per epoch: {config.poisson_lambda}")


if __name__ == "__main__":
    main()

