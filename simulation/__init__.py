"""HD-SMS executable prototype.

A working, reviewable, reproducible Python implementation of:
- SHA-256-based Sparse Merkle Tree (baseline)
- Hierarchical Delta Sparse Merkle Structuring (HD-SMS, proposed)

All commitments are real SHA-256 hashes. All proofs verify against the
published root. No analytical estimators, no hardcoded experimental values.
"""

__version__ = "1.0.0"
