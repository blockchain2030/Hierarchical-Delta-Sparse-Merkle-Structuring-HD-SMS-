"""
plot_generator.py

Plot generation utility for HD-SMS experimental results.

This script generates publication-ready comparison charts for:
- Update cost comparison
- Proof size comparison
- Storage overhead comparison
- Verification latency comparison

The default values match the experimental tables commonly used in the HD-SMS
evaluation framework. The script can also read custom CSV files if available.

Output files are saved in the /plots directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

import pandas as pd
import matplotlib.pyplot as plt


DEFAULT_UPDATE_COST = pd.DataFrame(
    {
        "n": ["10⁴", "10⁵", "10⁶", "10⁷"],
        "SMT": [14.2, 17.0, 20.1, 23.4],
        "Verkle": [15.1, 18.3, 21.5, 24.2],
        "HD-SMS": [8.1, 9.0, 10.2, 7.0],
    }
)

DEFAULT_PROOF_SIZE = pd.DataFrame(
    {
        "n": ["10⁴", "10⁵", "10⁶", "10⁷"],
        "SMT": [448, 576, 704, 832],
        "Verkle": [384, 512, 640, 768],
        "HD-SMS": [280, 340, 400, 316],
    }
)

DEFAULT_STORAGE_LATENCY = pd.DataFrame(
    {
        "n": ["10⁴", "10⁵", "10⁶", "10⁷"],
        "SMT_MB": [12, 78, 245, 412],
        "Verkle_MB": [14, 92, 298, 486],
        "HD_SMS_MB": [8, 52, 156, 218],
        "SMT_ms": [58, 76, 98, 120],
        "Verkle_ms": [72, 92, 118, 145],
        "HD_SMS_ms": [38, 48, 55, 67],
    }
)


def read_csv_or_default(path: Optional[str], default_df: pd.DataFrame) -> pd.DataFrame:
    if not path:
        return default_df.copy()

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    return pd.read_csv(csv_path)


def save_bar_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    title: str,
    y_label: str,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ax = df.plot(
        x=x_col,
        y=y_cols,
        kind="bar",
        figsize=(8, 5),
        width=0.75,
        rot=0,
    )

    ax.set_title(title)
    ax.set_xlabel("Account Population")
    ax.set_ylabel(y_label)
    ax.legend(title="Structure")
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.7)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()


def generate_update_cost_plot(output_dir: Path, input_csv: Optional[str] = None) -> Path:
    df = read_csv_or_default(input_csv, DEFAULT_UPDATE_COST)
    output_path = output_dir / "fig_update_cost.png"

    save_bar_chart(
        df=df,
        x_col="n",
        y_cols=["SMT", "Verkle", "HD-SMS"],
        title="Update Cost Comparison",
        y_label="Hash Operations per Update",
        output_path=output_path,
    )

    return output_path


def generate_proof_size_plot(output_dir: Path, input_csv: Optional[str] = None) -> Path:
    df = read_csv_or_default(input_csv, DEFAULT_PROOF_SIZE)
    output_path = output_dir / "fig_proof_size.png"

    save_bar_chart(
        df=df,
        x_col="n",
        y_cols=["SMT", "Verkle", "HD-SMS"],
        title="Proof Size Comparison",
        y_label="Proof Size (bytes)",
        output_path=output_path,
    )

    return output_path


def generate_storage_plot(output_dir: Path, input_csv: Optional[str] = None) -> Path:
    df = read_csv_or_default(input_csv, DEFAULT_STORAGE_LATENCY)
    output_path = output_dir / "fig_storage.png"

    save_bar_chart(
        df=df,
        x_col="n",
        y_cols=["SMT_MB", "Verkle_MB", "HD_SMS_MB"],
        title="Storage Overhead Benchmark",
        y_label="Storage Overhead (MB)",
        output_path=output_path,
    )

    return output_path


def generate_latency_plot(output_dir: Path, input_csv: Optional[str] = None) -> Path:
    df = read_csv_or_default(input_csv, DEFAULT_STORAGE_LATENCY)
    output_path = output_dir / "fig_latency.png"

    save_bar_chart(
        df=df,
        x_col="n",
        y_cols=["SMT_ms", "Verkle_ms", "HD_SMS_ms"],
        title="Verification Latency Comparison",
        y_label="Verification Latency (ms)",
        output_path=output_path,
    )

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate HD-SMS experimental comparison plots."
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="plots",
        help="Directory where generated plots will be saved.",
    )

    parser.add_argument(
        "--update-cost-csv",
        type=str,
        default=None,
        help="Optional CSV for update cost values.",
    )

    parser.add_argument(
        "--proof-size-csv",
        type=str,
        default=None,
        help="Optional CSV for proof size values.",
    )

    parser.add_argument(
        "--storage-latency-csv",
        type=str,
        default=None,
        help="Optional CSV for storage and latency values.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)

    generated_files = [
        generate_update_cost_plot(output_dir, args.update_cost_csv),
        generate_proof_size_plot(output_dir, args.proof_size_csv),
        generate_storage_plot(output_dir, args.storage_latency_csv),
        generate_latency_plot(output_dir, args.storage_latency_csv),
    ]

    print("Generated plots:")
    for file_path in generated_files:
        print(f"- {file_path}")


if __name__ == "__main__":
    main()
