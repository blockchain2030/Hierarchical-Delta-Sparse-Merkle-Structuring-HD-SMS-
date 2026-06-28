# HD-SMS Executable Prototype

A working Python implementation of **Hierarchical Delta Sparse Merkle
Structuring (HD-SMS)** and a Sparse Merkle Tree (SMT) baseline, with a
reproducible benchmark harness for micro-fraction token transfer
workloads.

## What this repository is

- A real implementation. Every commitment is a SHA-256 hash; every proof
  is constructed from sibling hashes; every verification recomputes the
  root and compares it to the published value.
- A reproducible benchmark. Three scenarios (single update, epoch-batch
  update, batch verify) are run over multiple seeds with 95% confidence
  intervals.
- A test suite (45 tests) covering correctness, tamper-resistance,
  batch invariants and edge cases.

## What this repository is NOT



## empirical results (default config, 5 seeds, 95% CIs)

The benchmark harness produces three CSVs. The summary below is the
result of running `python -m simulation.run_all` from a clean checkout
on a developer laptop.

### Scenario 1 — single-update workload (one commit per account update)

| n         | SMT hash ops/update | HD-SMS hash ops/update | Verdict |
|-----------|---------------------|------------------------|---------|
| 10,000    | 15.0                | 16.0                   | **SMT slightly faster** (one extra global-tree step in HD-SMS) |
| 100,000   | 18.0                | 19.0                   | **SMT slightly faster** |

| n         | SMT proof bytes | HD-SMS proof bytes | Verdict |
|-----------|-----------------|--------------------|---------|
| 10,000    | 480             | 624                | **SMT smaller** (single proof vs local+global proofs) |
| 100,000   | 576             | 720                | **SMT smaller** |

HD-SMS pays a constant overhead for its two-tree structure on
one-account-at-a-time workloads. This is the *expected* honest result —
there is no free lunch when each update propagates through both trees.

### Scenario 2 — epoch-batch updates (clustered workload)

When many account updates within an epoch are committed together,
HD-SMS amortises the global-tree update over all accounts in the same
partition. SMT has no analogous shared structure across distinct keys.

| n         | SMT ops/update | HD-SMS ops/update | HD-SMS reduction vs SMT |
|-----------|----------------|-------------------|-------------------------|
| 10,000    | 15.00          | 11.11             | **25.9%**               |
| 100,000   | 18.00          | 11.32             | **37.1%**               |

This is the regime where the partitioning design earns its overhead.
With realistic burst-locality (70% intra-partition by default), HD-SMS
beats SMT on the metric that matters for production rollup batching.

### Scenario 3 — batch verification within a partition (audit workload)

When a verifier checks many accounts in the same partition (regulatory
audit, multi-party validation), HD-SMS shares the global proof once
across the whole batch. SMT requires an independent proof per key.

| n         | SMT verify ms/account | HD-SMS verify ms/account | HD-SMS reduction vs SMT |
|-----------|-----------------------|--------------------------|-------------------------|
| 10,000    | 0.0224                | 0.0202                   | **9.7%**                |
| 100,000   | 0.0269                | 0.0201                   | **25.1%**               |

| n         | SMT bytes/account (batch) | HD-SMS bytes/account (batch) |
|-----------|--------------------------:|-----------------------------:|
| 10,000    | 480                       | 433.2                        |
| 100,000   | 576                       | 433.7                        |

HD-SMS's per-account proof footprint stays roughly flat in n because
the shared global proof is amortised across the batch.

### What the manuscript can honestly claim

- HD-SMS improves **batch-update cost by 26–37%** versus SMT on
  clustered micro-fraction workloads at n ∈ {10K, 100K}.
- HD-SMS improves **batch-verify latency by 10–25%** and **batch proof
  bytes by 9–25%** for intra-partition audits at the same scales.
- HD-SMS **does not** improve per-update cost on single-account
  workloads — and the paper should not claim otherwise.

These numbers are produced by the supplied benchmark from a clean run;
they are not hardcoded constants anywhere in the source.

## Repository structure

```
simulation/
  __init__.py
  crypto.py              SHA-256 domain-separated hash helpers
  smt.py                 Sparse Merkle Tree baseline (with batch verify)
  hd_sms.py              HD-SMS partitioned delta tree (with batch ops)
  workload_generator.py  Poisson / Zipf / log-normal workload generator
  benchmark.py           Multi-seed benchmark runner with 95% CIs
  plot_generator.py      Plots from CSVs only (no hardcoded values)
  run_all.py             One-command full pipeline
tests/
  test_crypto.py         SHA-256 helpers and domain separation
  test_smt.py            SMT correctness and tamper rejection
  test_hd_sms.py         HD-SMS correctness, batch invariants, tampering
  test_workload.py       Workload generator determinism and properties
results/                 benchmark_*.csv (regenerated by run_all)
plots/                   fig_*.png (regenerated from CSVs by plot_generator)
LICENSE                  MIT
SECURITY.md              Threat model and security argument for the
                         delta-encoded leaf and batch-verification scheme
REPRODUCIBILITY.md       Exact steps and environment for repro
CITATION.cff             Citation metadata
requirements.txt         Pinned Python dependencies
pyproject.toml           Package metadata
.gitignore
```

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the test suite (45 tests, ~0.2 s)
pytest

# 3. Run the full benchmark + generate plots (a few seconds at default config)
python -m simulation.run_all
```

Output appears in `results/` (CSV) and `plots/` (PNG).

## Running larger experiments

The defaults are intentionally small so a reviewer can verify everything
in seconds. For paper-quality numbers:

```bash
python -m simulation.benchmark \
  --accounts 10000 100000 1000000 \
  --epochs 50 \
  --lambda-updates 500 \
  --seeds 10 \
  --batch-verify-size 500 \
  --output-dir results
```

Note: `n = 1,000,000` allocates a depth-20 SMT and many partition
trees; expect minutes per seed.

## Security argument

The leaf encoding `H(account_id ‖ epoch ‖ delta ‖ previous_balance)`
binds a delta to a specific account, epoch, and prior state. This
closes the malleability gap a naive delta-only scheme would have
(otherwise two opposite-sign deltas in a batch could be re-ordered or
swapped between accounts without changing the aggregate). See
[SECURITY.md](SECURITY.md) for the full threat model, definitions of
binding for delta-encoded leaves, and a reduction sketch to SHA-256
collision resistance.

## Reproducibility

See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for the exact environment
(Python version, package versions, OS) and the commands that regenerate
every CSV and plot in `results/` and `plots/` from a clean checkout.

## Citation

If you use this code, please cite the manuscript and this repository.
See [CITATION.cff](CITATION.cff).

## License

MIT. See [LICENSE](LICENSE).
