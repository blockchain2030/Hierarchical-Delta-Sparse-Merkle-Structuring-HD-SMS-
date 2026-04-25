"""
verification_engine.py

Verification and proof-cost estimation engine for HD-SMS experiments.

This module simulates:
- Proof size estimation (bytes)
- Verification latency (ms)
- Batch verification efficiency
- Comparison with SMT and Verkle baselines

It uses workload + partition summary outputs.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Dict, List


class VerificationEngine:
    def __init__(self, branching_factor: int = 16):
        self.b = branching_factor

    def _logb(self, n: float) -> float:
        return math.log(max(n, 1), self.b)

    def estimate_smt_proof_size(self, n: int) -> float:
        return self._logb(n) * 32  # 32 bytes per hash

    def estimate_verkle_proof_size(self, n: int) -> float:
        return self._logb(n) * 28

    def estimate_hd_sms_proof_size(self, partition_size: int, k: int) -> float:
        local = self._logb(partition_size)
        global_part = self._logb(k)
        return (local + global_part) * 24

    def estimate_latency(self, proof_size: float) -> float:
        base = 0.02  # ms per byte approximation
        return round(proof_size * base, 3)

    def batch_efficiency(self, count: int) -> float:
        if count <= 1:
            return 1.0
        return round(1 / math.log(count + 1), 3)


def read_partition_summary(path: Path) -> List[Dict[str, str]]:
    rows = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def write_verification_results(
    partition_summary_path: Path,
    output_path: Path,
    branching_factor: int,
) -> None:
    engine = VerificationEngine(branching_factor)
    rows = read_partition_summary(partition_summary_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "epoch",
        "smt_proof_bytes",
        "verkle_proof_bytes",
        "hd_sms_proof_bytes",
        "smt_latency_ms",
        "verkle_latency_ms",
        "hd_sms_latency_ms",
        "batch_efficiency",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            n = int(float(row["active_accounts"]))
            k = int(float(row["active_partitions"]))
            partition_size = max(1, n // max(k, 1))

            smt_size = engine.estimate_smt_proof_size(n)
            verkle_size = engine.estimate_verkle_proof_size(n)
            hd_size = engine.estimate_hd_sms_proof_size(partition_size, k)

            writer.writerow(
                {
                    "epoch": row["epoch"],
                    "smt_proof_bytes": round(smt_size, 2),
                    "verkle_proof_bytes": round(verkle_size, 2),
                    "hd_sms_proof_bytes": round(hd_size, 2),
                    "smt_latency_ms": engine.estimate_latency(smt_size),
                    "verkle_latency_ms": engine.estimate_latency(verkle_size),
                    "hd_sms_latency_ms": engine.estimate_latency(hd_size),
                    "batch_efficiency": engine.batch_efficiency(n),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verification and proof simulation engine")
    parser.add_argument("--input", type=str, default="results/partition_summary.csv")
    parser.add_argument("--output", type=str, default="results/verification_results.csv")
    parser.add_argument("--branching-factor", type=int, default=16)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    write_verification_results(
        partition_summary_path=Path(args.input),
        output_path=Path(args.output),
        branching_factor=args.branching_factor,
    )

    print(f"Verification results saved to: {args.output}")


if __name__ == "__main__":
    main()
