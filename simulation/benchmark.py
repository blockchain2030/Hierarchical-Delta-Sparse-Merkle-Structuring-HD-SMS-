"""Benchmark runner for executable SMT and HD-SMS prototypes.

Three benchmark scenarios are reported, each over multiple seeds so 95%
confidence intervals can be computed:

  1. SINGLE-UPDATE        per-update hash ops, proof bytes, verify ms
                          for one-account-at-a-time updates.
                          (The naive workload; SMT is competitive here.)

  2. EPOCH-BATCH-UPDATE   per-update hash ops when many accounts in the
                          same partition are updated together in one
                          epoch. HD-SMS amortises the global-tree update.

  3. BATCH-VERIFY         per-account verify ms when many accounts in
                          the same partition are audited together.
                          HD-SMS shares the global proof, SMT cannot.

Every number written to CSV is the mean across `--seeds` independent
runs together with a 95% half-width based on Student's t. NO HARD-CODED
EXPERIMENTAL VALUES APPEAR IN THIS FILE.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics as stats
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from .crypto import i128
from .hd_sms import HDSMS
from .smt import SparseMerkleTree
from .workload_generator import MicroFractionWorkloadGenerator, WorkloadConfig


# ===========================================================================
#  Statistical helpers
# ===========================================================================
# Student's t critical values at 95% for small n; for n>=11 we use the
# normal approximation (1.96), which is conservative.
_T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447,
        8: 2.365, 9: 2.306, 10: 2.262}


def mean_ci(values: List[float]) -> Tuple[float, float]:
    """Return (mean, 95% half-width). If n<2, half-width is 0."""
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    mean = stats.fmean(values)
    if n == 1:
        return mean, 0.0
    sd = stats.stdev(values)
    t = _T95.get(n, 1.96)
    return mean, t * sd / math.sqrt(n)


def account_depth(account_count: int) -> int:
    """SMT depth required to address all accounts."""
    return max(1, math.ceil(math.log2(account_count)))


# ===========================================================================
#  Scenario 1 -- single update per call
# ===========================================================================
def run_single_update_scenario(account_count: int, partition_size: int,
                               epochs: int, lambda_updates: int, seed: int,
                               proof_samples: int) -> Dict[str, float]:
    """One commit per account-update; both trees re-rooted after each.

    This is the worst case for HD-SMS (two trees to update each time)
    and the natural case for SMT.
    """
    cfg = WorkloadConfig(
        account_count=account_count,
        partition_size=partition_size,
        epochs=epochs,
        poisson_lambda=lambda_updates,
        seed=seed,
    )
    workload = MicroFractionWorkloadGenerator(cfg).generate()

    smt = SparseMerkleTree(account_depth(account_count))
    hd = HDSMS(account_count=account_count, partition_size=partition_size)

    smt_ops: List[int] = []
    hd_ops: List[int] = []
    touched = set()

    for row in workload:
        account_id = int(row["account_id"])
        delta = int(row["delta_units"])
        epoch = int(row["epoch"])
        touched.add(account_id)

        # SMT baseline: commit to absolute balance (the standard SMT semantic)
        previous = int.from_bytes(
            smt.values.get(account_id, i128(0)), "big", signed=True
        ) if account_id in smt.values else 0
        new_value = max(0, previous + delta)
        smt_ops.append(smt.update(account_id, i128(new_value)))
        hd_ops.append(hd.update_delta(account_id, delta, epoch))

    # Sample proofs and measure verification time
    sample = list(touched)[:proof_samples]
    smt_sizes, hd_sizes, smt_verify_ms, hd_verify_ms = [], [], [], []
    for account_id in sample:
        sp = smt.prove(account_id)
        hp = hd.prove(account_id)
        smt_sizes.append(sp.byte_size())
        hd_sizes.append(hp.byte_size())
        t0 = time.perf_counter_ns()
        assert SparseMerkleTree.verify(smt.root, sp), "SMT verify failed"
        smt_verify_ms.append((time.perf_counter_ns() - t0) / 1_000_000)
        t0 = time.perf_counter_ns()
        assert HDSMS.verify(hd.root, hp), "HD-SMS verify failed"
        hd_verify_ms.append((time.perf_counter_ns() - t0) / 1_000_000)

    return {
        "updates": len(workload),
        "touched_accounts": len(touched),
        "SMT_hash_ops_per_update": stats.fmean(smt_ops),
        "HD_SMS_hash_ops_per_update": stats.fmean(hd_ops),
        "SMT_proof_bytes": stats.fmean(smt_sizes) if smt_sizes else 0.0,
        "HD_SMS_proof_bytes": stats.fmean(hd_sizes) if hd_sizes else 0.0,
        "SMT_storage_MB": smt.storage_bytes() / 1_000_000,
        "HD_SMS_storage_MB": hd.storage_bytes() / 1_000_000,
        "SMT_verify_ms": stats.fmean(smt_verify_ms) if smt_verify_ms else 0.0,
        "HD_SMS_verify_ms": stats.fmean(hd_verify_ms) if hd_verify_ms else 0.0,
        "proof_samples": len(sample),
    }


# ===========================================================================
#  Scenario 2 -- epoch-grouped batch updates
# ===========================================================================
def run_batch_update_scenario(account_count: int, partition_size: int,
                              epochs: int, lambda_updates: int,
                              seed: int) -> Dict[str, float]:
    """All updates in one epoch are committed together.

    For HD-SMS this means: one global-tree update per affected partition
    per epoch (not per account). This is where the partitioning design
    pays for itself when updates are clustered.

    SMT has no analogous shared structure across keys, so its batch cost
    equals the sum of its single-update costs (provided as a fair
    baseline using the same workload).
    """
    cfg = WorkloadConfig(
        account_count=account_count,
        partition_size=partition_size,
        epochs=epochs,
        poisson_lambda=lambda_updates,
        seed=seed,
    )
    workload = MicroFractionWorkloadGenerator(cfg).generate()
    epochs_to_updates: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for row in workload:
        epochs_to_updates[int(row["epoch"])].append(
            (int(row["account_id"]), int(row["delta_units"]))
        )

    smt = SparseMerkleTree(account_depth(account_count))
    hd = HDSMS(account_count=account_count, partition_size=partition_size)

    smt_total_ops = 0
    hd_total_ops = 0
    hd_global_ops_only = 0
    total_updates = 0

    for epoch, updates in epochs_to_updates.items():
        # SMT: no shared structure across keys
        for account_id, delta in updates:
            previous = int.from_bytes(
                smt.values.get(account_id, i128(0)), "big", signed=True
            ) if account_id in smt.values else 0
            new_value = max(0, previous + delta)
            smt_total_ops += smt.update(account_id, i128(new_value))
        # HD-SMS: one global update per affected partition
        report = hd.update_batch_in_epoch(updates, epoch=epoch)
        hd_total_ops += report["total_hash_ops"]
        hd_global_ops_only += report["global_hash_ops"]
        total_updates += len(updates)

    return {
        "batch_updates_total": total_updates,
        "SMT_total_hash_ops_batch": smt_total_ops,
        "HD_SMS_total_hash_ops_batch": hd_total_ops,
        "HD_SMS_global_ops_only": hd_global_ops_only,
        "SMT_avg_hash_ops_per_update_batch": smt_total_ops / max(total_updates, 1),
        "HD_SMS_avg_hash_ops_per_update_batch": hd_total_ops / max(total_updates, 1),
    }


# ===========================================================================
#  Scenario 3 -- batch verification within a partition
# ===========================================================================
def run_batch_verify_scenario(account_count: int, partition_size: int,
                              batch_size: int, seed: int) -> Dict[str, float]:
    """Set up state with many accounts in one partition, then audit a
    batch of them all at once.

    HD-SMS shares the global path across all proofs in the batch; SMT
    requires an independent proof per key. This is the structural reason
    HD-SMS can beat SMT on regulatory / audit workloads.
    """
    # Build a fresh state with `batch_size` accounts active inside ONE
    # partition. Deterministic seeding so results are reproducible.
    import random as _r
    rng = _r.Random(seed)
    target_partition = rng.randrange(0, max(1, account_count // partition_size))
    start = target_partition * partition_size
    end = min(start + partition_size, account_count)
    candidate_accounts = list(range(start, end))
    rng.shuffle(candidate_accounts)
    active_accounts = candidate_accounts[: min(batch_size, len(candidate_accounts))]

    smt = SparseMerkleTree(account_depth(account_count))
    hd = HDSMS(account_count=account_count, partition_size=partition_size)

    # Populate with some balance so proofs are non-trivial
    for i, account_id in enumerate(active_accounts):
        delta = (i + 1) * 1000  # deterministic positive deltas
        new_value = delta
        smt.update(account_id, i128(new_value))
        hd.update_delta(account_id, delta, epoch=1)

    # ----- SMT batch verify: independent proofs -----
    smt_proofs = [smt.prove(a) for a in active_accounts]
    smt_total_bytes = sum(p.byte_size() for p in smt_proofs)
    t0 = time.perf_counter_ns()
    assert SparseMerkleTree.verify_batch(smt.root, smt_proofs), "SMT batch verify failed"
    smt_verify_ms = (time.perf_counter_ns() - t0) / 1_000_000

    # ----- HD-SMS batch verify: shared global proof -----
    hd_batches = hd.prove_batch(active_accounts)
    hd_total_bytes = sum(b.byte_size() for b in hd_batches)
    t0 = time.perf_counter_ns()
    for batch in hd_batches:
        assert HDSMS.verify_batch(hd.root, batch), "HD-SMS batch verify failed"
    hd_verify_ms = (time.perf_counter_ns() - t0) / 1_000_000

    return {
        "batch_size": len(active_accounts),
        "SMT_batch_proof_bytes_total": smt_total_bytes,
        "HD_SMS_batch_proof_bytes_total": hd_total_bytes,
        "SMT_batch_verify_ms": smt_verify_ms,
        "HD_SMS_batch_verify_ms": hd_verify_ms,
        "SMT_bytes_per_account": smt_total_bytes / len(active_accounts),
        "HD_SMS_bytes_per_account": hd_total_bytes / len(active_accounts),
        "SMT_verify_ms_per_account": smt_verify_ms / len(active_accounts),
        "HD_SMS_verify_ms_per_account": hd_verify_ms / len(active_accounts),
    }


# ===========================================================================
#  Multi-seed orchestration
# ===========================================================================
def aggregate_runs(runs: List[Dict[str, float]]) -> Dict[str, float]:
    """Collapse a list of per-seed runs to {metric_mean, metric_ci95}."""
    if not runs:
        return {}
    keys = list(runs[0].keys())
    out: Dict[str, float] = {}
    for k in keys:
        values = [float(r[k]) for r in runs]
        mean, half = mean_ci(values)
        out[f"{k}_mean"] = round(mean, 6)
        out[f"{k}_ci95"] = round(half, 6)
    return out


# ===========================================================================
#  CLI
# ===========================================================================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run HD-SMS benchmark suite.")
    p.add_argument("--accounts", nargs="+", type=int,
                   default=[10_000, 100_000],
                   help="Account counts to sweep")
    p.add_argument("--partition-size", type=int, default=1_000)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--lambda-updates", type=int, default=200)
    p.add_argument("--proof-samples", type=int, default=100,
                   help="Number of distinct accounts to sample for single-proof timing")
    p.add_argument("--batch-verify-size", type=int, default=200,
                   help="Number of accounts per batch in batch-verify scenario")
    p.add_argument("--seeds", type=int, default=5,
                   help="Independent seeds per (account_count, scenario)")
    p.add_argument("--base-seed", type=int, default=42)
    p.add_argument("--output-dir", type=str, default="results")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    single_rows: List[Dict[str, object]] = []
    batch_update_rows: List[Dict[str, object]] = []
    batch_verify_rows: List[Dict[str, object]] = []

    for n in args.accounts:
        print(f"\n=== n = {n:,} accounts (seeds={args.seeds}) ===")

        # Scenario 1: single updates
        runs1 = []
        for s in range(args.seeds):
            runs1.append(run_single_update_scenario(
                n, args.partition_size, args.epochs,
                args.lambda_updates, args.base_seed + s, args.proof_samples
            ))
        agg1 = aggregate_runs(runs1)
        agg1["n"] = n
        agg1["seeds"] = args.seeds
        single_rows.append(agg1)
        print(f"  single-update    SMT {agg1['SMT_hash_ops_per_update_mean']:.2f}±{agg1['SMT_hash_ops_per_update_ci95']:.2f} ops "
              f"vs HD-SMS {agg1['HD_SMS_hash_ops_per_update_mean']:.2f}±{agg1['HD_SMS_hash_ops_per_update_ci95']:.2f} ops")

        # Scenario 2: batch updates
        runs2 = []
        for s in range(args.seeds):
            runs2.append(run_batch_update_scenario(
                n, args.partition_size, args.epochs,
                args.lambda_updates, args.base_seed + s
            ))
        agg2 = aggregate_runs(runs2)
        agg2["n"] = n
        agg2["seeds"] = args.seeds
        batch_update_rows.append(agg2)
        print(f"  epoch-batch upd  SMT {agg2['SMT_avg_hash_ops_per_update_batch_mean']:.2f} ops "
              f"vs HD-SMS {agg2['HD_SMS_avg_hash_ops_per_update_batch_mean']:.2f} ops "
              f"({(1 - agg2['HD_SMS_avg_hash_ops_per_update_batch_mean'] / agg2['SMT_avg_hash_ops_per_update_batch_mean']) * 100:+.1f}% vs SMT)")

        # Scenario 3: batch verify
        runs3 = []
        for s in range(args.seeds):
            runs3.append(run_batch_verify_scenario(
                n, args.partition_size, args.batch_verify_size, args.base_seed + s
            ))
        agg3 = aggregate_runs(runs3)
        agg3["n"] = n
        agg3["seeds"] = args.seeds
        batch_verify_rows.append(agg3)
        print(f"  batch-verify     SMT {agg3['SMT_verify_ms_per_account_mean']:.4f} ms/acct "
              f"vs HD-SMS {agg3['HD_SMS_verify_ms_per_account_mean']:.4f} ms/acct "
              f"({(1 - agg3['HD_SMS_verify_ms_per_account_mean'] / max(agg3['SMT_verify_ms_per_account_mean'], 1e-9)) * 100:+.1f}% vs SMT)")

    # Write CSVs
    def write(path: Path, rows: List[Dict[str, object]]) -> None:
        if not rows:
            return
        fieldnames = ["n", "seeds"] + [k for k in rows[0].keys() if k not in ("n", "seeds")]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    write(out_dir / "benchmark_single_update.csv", single_rows)
    write(out_dir / "benchmark_batch_update.csv", batch_update_rows)
    write(out_dir / "benchmark_batch_verify.csv", batch_verify_rows)
    print(f"\nwrote {out_dir}/benchmark_single_update.csv")
    print(f"wrote {out_dir}/benchmark_batch_update.csv")
    print(f"wrote {out_dir}/benchmark_batch_verify.csv")


if __name__ == "__main__":
    main()
