"""Workload generator for micro-fraction token transfer experiments.

Produces realistic update streams shaped by:
  - Poisson(lambda)  for the number of updates per epoch
  - Zipfian(alpha)   for global account sampling (hot accounts)
  - Log-normal(mu, sigma) for delta magnitudes (most updates are tiny)
  - Intra-partition burst ratio: probability that an update lands in the
    same partition as the burst anchor, modelling temporal locality
    (e.g. dividend events, group settlements)

The generator is deterministic given a seed and is independent of the
commitment-structure implementation under test.
"""
from __future__ import annotations

import argparse
import csv
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np


@dataclass
class WorkloadConfig:
    account_count: int = 10_000
    partition_size: int = 1_000
    epochs: int = 20
    poisson_lambda: int = 500
    zipf_alpha: float = 1.2
    lognormal_mu: float = -12.0
    lognormal_sigma: float = 2.0
    intra_partition_ratio: float = 0.70
    total_supply_units: int = 10 ** 12
    seed: int = 42

    def __post_init__(self) -> None:
        if self.account_count <= 0:
            raise ValueError("account_count must be positive")
        if self.partition_size <= 0:
            raise ValueError("partition_size must be positive")
        if not 0.0 <= self.intra_partition_ratio <= 1.0:
            raise ValueError("intra_partition_ratio must be in [0, 1]")


class MicroFractionWorkloadGenerator:
    """Deterministic generator of synthetic micro-fraction update streams."""

    def __init__(self, config: WorkloadConfig):
        self.config = config
        # Two independent RNG streams so changes to one path do not perturb the
        # other across versions; both seeded from the same root for determinism.
        self._py_rng = random.Random(config.seed)
        self._np_rng = np.random.default_rng(config.seed)

    # ----- samplers -----
    def _partition_of(self, account_id: int) -> int:
        return account_id // self.config.partition_size

    def _sample_account_zipf(self) -> int:
        # numpy's zipf draws from 1..inf; we shift to 0-indexed and reject
        # samples that fall outside the account space.
        while True:
            sampled = int(self._np_rng.zipf(self.config.zipf_alpha)) - 1
            if 0 <= sampled < self.config.account_count:
                return sampled

    def _sample_account_from_partition(self, partition_id: int) -> int:
        start = partition_id * self.config.partition_size
        end = min(start + self.config.partition_size, self.config.account_count)
        if start >= end:
            return self._sample_account_zipf()
        return self._py_rng.randint(start, end - 1)

    def _sample_delta_units(self) -> int:
        # Log-normal with mu = -12, sigma = 2 puts the bulk of magnitude in the
        # 1e-6 .. 1e-3 fraction-of-supply range, with a heavy tail of larger
        # transfers. Scale by total_supply_units to get integer units.
        raw = float(self._np_rng.lognormal(self.config.lognormal_mu, self.config.lognormal_sigma))
        units = max(1, int(raw * self.config.total_supply_units))
        # Random sign so each account experiences both credits and debits.
        return -units if self._py_rng.random() < 0.5 else units

    # ----- generation -----
    def generate_epoch(self, epoch: int) -> List[Dict[str, int]]:
        update_count = int(self._np_rng.poisson(self.config.poisson_lambda))
        if update_count == 0:
            return []
        anchor = self._sample_account_zipf()
        anchor_partition = self._partition_of(anchor)
        rows: List[Dict[str, int]] = []
        for update_index in range(update_count):
            local = self._py_rng.random() < self.config.intra_partition_ratio
            account_id = (self._sample_account_from_partition(anchor_partition)
                          if local else self._sample_account_zipf())
            delta = self._sample_delta_units()
            rows.append({
                "epoch": epoch,
                "update_index": update_index,
                "account_id": account_id,
                "partition_id": self._partition_of(account_id),
                "delta_units": delta,
                "abs_delta_units": abs(delta),
                "is_intra_partition_burst": int(local),
            })
        return rows

    def generate(self) -> List[Dict[str, int]]:
        rows: List[Dict[str, int]] = []
        for epoch in range(self.config.epochs):
            rows.extend(self.generate_epoch(epoch))
        return rows

    def write_csv(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.generate()
        if not rows:
            raise RuntimeError("generated empty workload; check configuration")
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        # Persist the exact configuration alongside the data for full provenance.
        config_path = output_path.with_suffix(".config.csv")
        with config_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["parameter", "value"])
            for k, v in asdict(self.config).items():
                writer.writerow([k, v])


# ----- CLI -----
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate a micro-fraction workload CSV.")
    p.add_argument("--account-count", type=int, default=10_000)
    p.add_argument("--partition-size", type=int, default=1_000)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--lambda-updates", type=int, default=500)
    p.add_argument("--zipf-alpha", type=float, default=1.2)
    p.add_argument("--intra-partition-ratio", type=float, default=0.70)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", type=str, default="data/generated_workloads.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = WorkloadConfig(
        account_count=args.account_count,
        partition_size=args.partition_size,
        epochs=args.epochs,
        poisson_lambda=args.lambda_updates,
        zipf_alpha=args.zipf_alpha,
        intra_partition_ratio=args.intra_partition_ratio,
        seed=args.seed,
    )
    MicroFractionWorkloadGenerator(cfg).write_csv(Path(args.output))
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
