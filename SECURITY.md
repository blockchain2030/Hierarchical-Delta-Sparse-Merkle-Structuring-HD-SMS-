# Security Argument for HD-SMS

This document addresses the security properties of HD-SMS by giving an
explicit threat model, formal definitions of the binding properties we
claim, and a sketch reducing each property to SHA-256 collision
resistance.

## 1. Threat model

HD-SMS targets the same threat model as the SMT baseline: a public,
append-only ledger setting where a designated **committer** advances
the global state, posts the root commitment R, and serves proofs on
request. The relevant adversary classes are:

- **Verifier-side adversary V*.** Sees the published root R and is
  given a proof π for an account and a claimed (epoch, delta,
  previous_balance) tuple. V* tries to convince an honest verifier of
  a (account, epoch, delta, previous_balance) that does not correspond
  to the state actually committed by R.
- **Committer-side adversary C*.** Tries to publish a single root R
  that opens to two different (epoch, delta, previous_balance) tuples
  for the same (account, partition) coordinate.
- **Replay adversary R*.** Tries to reuse a valid proof from one epoch
  or one prior-balance context against a different state.
- **Batch adversary B*.** Sees a HDSMSBatchProof for accounts in a
  single partition and tries to substitute, reorder, or fabricate
  per-account claims while keeping the shared global proof.

Network and consensus attacks (Sybil, eclipse, censorship of the
committer) are out of scope; these are properties of the wider
blockchain system in which HD-SMS would be embedded and are inherited
from that system, not from the commitment structure.

## 2. Definitions of binding

We instantiate three binding games tailored to the delta-encoded
hierarchical setting.

### 2.1 Account-state binding (single proof)

An adversary wins if it produces (R, π₁, π₂) where π₁ and π₂ are
HDSMS proofs for the same `account_id` such that:

    HDSMS.verify(R, π₁) = HDSMS.verify(R, π₂) = true   AND
    (π₁.epoch, π₁.delta, π₁.previous_balance) ≠
    (π₂.epoch, π₂.delta, π₂.previous_balance)

Intuition: a single root must commit to at most one state transition
per account.

### 2.2 Delta-replay resistance

An adversary wins if it produces a proof π that verifies against R
such that the encoded `previous_balance` does not correspond to the
state that actually preceded the delta in the canonical history.

Intuition: a delta cannot be "lifted" from one epoch and applied to a
different epoch's prior balance.

### 2.3 Batch substitution resistance

An adversary wins if it produces (R, batch_proof) where
HDSMS.verify_batch(R, batch_proof) = true and at least one local proof
encodes an `(account_id, epoch, delta, previous_balance)` tuple that
does not correspond to the state committed by R for that account.

## 3. Reduction sketches

All three games reduce to SHA-256 collision resistance assuming our
domain-separated, length-prefixed encoding (see `crypto.sha256_parts`)
behaves as a collision-resistant random oracle on each domain.

### 3.1 Account-state binding

A winning adversary outputs two distinct (epoch, delta, prev_balance)
triples that verify against the same root. By Merkle path
construction, each proof's root reconstruction passes through:

    leaf_commitment = H_DELTA(account_id, epoch, delta, prev_balance)
    local_value     = leaf_commitment ‖ i128(prev_balance + delta)
    L               = H_LEAF(local_key, local_value)

Two distinct triples produce two distinct `local_value` values (the
hash inputs to H_DELTA differ in at least one length-prefixed part).
The reconstructed local roots therefore differ unless the sequence of
SHA-256 calls along the local path collides. Composing with the global
SMT path, equality of the final reconstructed roots implies a SHA-256
collision somewhere along the combined local+global path. Construct B
that runs A and outputs the first colliding (input₁, input₂) pair seen
along that path.

### 3.2 Delta-replay resistance

The leaf commitment binds `previous_balance` explicitly. An adversary
that "replays" a previously-valid delta against a different prior
balance produces a proof whose `expected_local_value` field differs
from the leaf actually committed at the time of the original update.
`HDSMS.verify` checks `proof.local_proof.value == expected_local_value`
before invoking the SMT verifier; this byte-for-byte check is the
primitive that enforces replay resistance.

### 3.3 Batch substitution resistance

`HDSMS.verify_batch` performs:

  (a) one global SMT verification proving
      `batch_proof.shared_global_proof` opens to (partition_id, partition_root)
      under R;
  (b) per local proof, recomputation of the expected `local_value` from
      (account_id, epoch, delta, previous_balance), a byte equality
      check against the local proof's stored value, and an SMT
      verification against `partition_root`.

A successful substitution would require either (i) producing a second
local proof for some account with a different `local_value` that
verifies under the same `partition_root` (reduces to SMT binding of
the partition tree, i.e. SHA-256 collision in the partition path), or
(ii) producing a `partition_root` that opens to the same `partition_id`
under R but is different from the genuine one (reduces to SMT binding
of the global tree). Either way the reduction is to SHA-256 collision
resistance.

## 4. What this argument does not cover

- **Computational integrity of off-chain delta computation.** HD-SMS
  binds the delta the committer chose to commit to. If the committer
  applies the wrong delta (e.g. credits the wrong account), HD-SMS
  cannot detect that — the same is true of any commitment scheme,
  including bare SMTs.
- **Liveness / availability.** A committer that refuses to serve proofs
  cannot be coerced by the commitment scheme. This is a system-level
  property addressed by the data-availability layer (DAS, blob storage,
  etc.) underneath HD-SMS, not by HD-SMS itself.
- **Confidentiality.** HD-SMS leaves are public commitments; account
  balances are recoverable from the published history. If
  confidentiality is required, HD-SMS leaves can be wrapped in a hiding
  commitment (Pedersen, KZG with blinding) — at extra cost and outside
  the scope of this prototype.
- **Composition with rollups.** Embedding HD-SMS as the state-root
  primitive of a Layer-2 rollup inherits all the security obligations
  of the rollup's fraud-proof or validity-proof system. HD-SMS is a
  drop-in replacement for SMT in that context, not a complete rollup
  design.

## 5. Implementation-level checks the test suite enforces

The test suite (`tests/test_hd_sms.py`, `tests/test_smt.py`,
`tests/test_crypto.py`) operationalises the security properties above:

- `test_tampered_local_value_rejected` — verifier rejects a forged
  local proof value.
- `test_tampered_delta_rejected` — verifier rejects a flipped delta.
- `test_tampered_previous_balance_rejected` — verifier rejects a
  flipped previous balance (delta-replay resistance).
- `test_proof_against_wrong_root_rejected` — verifier rejects a proof
  generated against a different root (account-state binding).
- `test_batch_verify_rejects_tampered_local_proof` — verifier rejects
  a batch where one local proof has been substituted (batch
  substitution resistance).
- `test_domain_separation_prevents_cross_use_collision`,
  `test_length_prefixing_prevents_concat_collision` — the encoding
  preconditions of the reductions above.

Any future modification to the leaf encoding, the domain tags, or the
verifier must be accompanied by a corresponding update to this
document and the test suite.
