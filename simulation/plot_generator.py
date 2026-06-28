"""Generate plots from benchmark CSVs only.

No hardcoded experimental values appear in this module. If the
benchmark CSVs are missing, the script fails so figures can never be
generated from constants.

Three plots are produced, matching the three benchmark scenarios:
  - fig_single_update.png  per-update hash ops with 95% CI bars
  - fig_batch_update.png   per-update hash ops in batch mode
  - fig_batch_verify.png   per-account verify time in batch mode
Plus a proof-bytes and storage-MB plot from the single-update results.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _load(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Benchmark CSV not found: {path}. Run `python -m simulation.benchmark` first."
        )
    return pd.read_csv(path)


def _bar(ax, df: pd.DataFrame, x_label_col: str, metrics: list, errs: list,
         series_labels: list, title: str, ylabel: str) -> None:
    x = np.arange(len(df))
    width = 0.38
    for i, (m, e, lbl) in enumerate(zip(metrics, errs, series_labels)):
        offset = (i - (len(metrics) - 1) / 2.0) * width
        ax.bar(x + offset, df[m], width, yerr=df[e] if e in df.columns else None,
               label=lbl, capsize=4)
    ax.set_xticks(x)
    ax.set_xticklabels(df[x_label_col])
    ax.set_xlabel("Number of accounts (n)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.6)


def plot_single_update(in_path: Path, out_dir: Path) -> None:
    df = _load(in_path).copy()
    df["n_label"] = df["n"].map(lambda v: f"{int(v):,}")

    # Update cost
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_hash_ops_per_update_mean", "HD_SMS_hash_ops_per_update_mean"],
         ["SMT_hash_ops_per_update_ci95", "HD_SMS_hash_ops_per_update_ci95"],
         ["SMT", "HD-SMS"],
         "Per-update hash operations (single-update scenario)",
         "SHA-256 invocations per update")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_single_update.png", dpi=300)
    plt.close(fig)

    # Proof size
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_proof_bytes_mean", "HD_SMS_proof_bytes_mean"],
         ["SMT_proof_bytes_ci95", "HD_SMS_proof_bytes_ci95"],
         ["SMT", "HD-SMS"],
         "Single-account proof size",
         "Proof bytes")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_proof_size.png", dpi=300)
    plt.close(fig)

    # Storage
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_storage_MB_mean", "HD_SMS_storage_MB_mean"],
         ["SMT_storage_MB_ci95", "HD_SMS_storage_MB_ci95"],
         ["SMT", "HD-SMS"],
         "In-memory storage after benchmark",
         "Storage (MB)")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_storage.png", dpi=300)
    plt.close(fig)

    # Single-proof verify latency
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_verify_ms_mean", "HD_SMS_verify_ms_mean"],
         ["SMT_verify_ms_ci95", "HD_SMS_verify_ms_ci95"],
         ["SMT", "HD-SMS"],
         "Single-proof verify latency",
         "Verify time (ms per proof)")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_single_verify.png", dpi=300)
    plt.close(fig)


def plot_batch_update(in_path: Path, out_dir: Path) -> None:
    df = _load(in_path).copy()
    df["n_label"] = df["n"].map(lambda v: f"{int(v):,}")
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_avg_hash_ops_per_update_batch_mean", "HD_SMS_avg_hash_ops_per_update_batch_mean"],
         ["SMT_avg_hash_ops_per_update_batch_ci95", "HD_SMS_avg_hash_ops_per_update_batch_ci95"],
         ["SMT", "HD-SMS"],
         "Epoch-batch update cost (hash ops per update)",
         "SHA-256 invocations per update")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_batch_update.png", dpi=300)
    plt.close(fig)


def plot_batch_verify(in_path: Path, out_dir: Path) -> None:
    df = _load(in_path).copy()
    df["n_label"] = df["n"].map(lambda v: f"{int(v):,}")
    fig, ax = plt.subplots(figsize=(8, 5))
    _bar(ax, df, "n_label",
         ["SMT_verify_ms_per_account_mean", "HD_SMS_verify_ms_per_account_mean"],
         ["SMT_verify_ms_per_account_ci95", "HD_SMS_verify_ms_per_account_ci95"],
         ["SMT", "HD-SMS"],
         "Batch-verify latency (per-account, within partition)",
         "Verify time (ms per account)")
    plt.tight_layout()
    plt.savefig(out_dir / "fig_batch_verify.png", dpi=300)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default="results")
    p.add_argument("--output-dir", default="plots")
    args = p.parse_args()
    in_dir = Path(args.results_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_single_update(in_dir / "benchmark_single_update.csv", out_dir)
    plot_batch_update(in_dir / "benchmark_batch_update.csv", out_dir)
    plot_batch_verify(in_dir / "benchmark_batch_verify.csv", out_dir)
    print(f"wrote plots to {out_dir}")


if __name__ == "__main__":
    main()
