"""One-command reproducibility entry point.

Runs the full benchmark suite with multiple seeds and 95% CIs, then
generates plots from the resulting CSVs. Designed so that:

    python -m simulation.run_all

regenerates every artifact in `results/` and `plots/` from scratch.
"""
from __future__ import annotations

import subprocess
import sys


def run(cmd: list) -> None:
    print("$", " ".join(cmd))
    subprocess.check_call(cmd)


def main() -> None:
    # Benchmark sweep: small-default config, finishes in seconds.
    # Increase --accounts, --epochs, --seeds for stronger experiments.
    run([
        sys.executable, "-m", "simulation.benchmark",
        "--accounts", "10000", "100000",
        "--epochs", "5",
        "--lambda-updates", "200",
        "--seeds", "5",
        "--batch-verify-size", "200",
        "--output-dir", "results",
    ])
    run([
        sys.executable, "-m", "simulation.plot_generator",
        "--results-dir", "results",
        "--output-dir", "plots",
    ])


if __name__ == "__main__":
    main()
