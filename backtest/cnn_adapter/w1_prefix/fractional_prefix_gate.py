"""可信 prefix proof 门禁，由所有情景绩效入口共用。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

TRUSTED_PREFIX_PROOF_SHA256: str | None = None
TRUSTED_PREFIX_ATTESTATOR_SHA256: str | None = None
BASE_HEAD = "ce7d1c6e0bd64136f10759412c55f6da410f128f"


def validate_prefix_proof(path: Path | None, expected_sha256: str | None) -> None:
    """校验硬编码可信 pin、文件字节及完整前缀裁决字段。"""
    if TRUSTED_PREFIX_PROOF_SHA256 is None:
        raise ValueError("prefix proof SHA is not independently pinned; performance is locked")
    if path is None or expected_sha256 is None:
        raise ValueError("prefix proof file and SHA256 are required")
    trusted = TRUSTED_PREFIX_PROOF_SHA256.lower()
    if expected_sha256.lower() != trusted:
        raise ValueError("caller prefix SHA does not match the trusted pin")
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("prefix proof must be a readable file no larger than 1MB")
    proof_bytes = path.read_bytes()
    if hashlib.sha256(proof_bytes).hexdigest() != trusted:
        raise ValueError("prefix proof bytes do not match the trusted pin")
    proof = json.loads(proof_bytes)
    if not isinstance(proof, dict) or (
        proof.get("schema_version") != "w1_prefix_machine_proof_v1"
        or proof.get("status") != "PASS"
        or proof.get("base_head") != BASE_HEAD
        or proof.get("through_date") != "2021-06-07"
        or proof.get("canonical_prefix_match") is not True
        or proof.get("floor_ceil_prefix_match") is not True
    ):
        raise ValueError("canonical W1 prefix proof is incomplete or not PASS")
    proof_sha = proof.get("proof_sha256")
    unsigned = {key: value for key, value in proof.items() if key != "proof_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str).encode("utf-8")
    if proof_sha != hashlib.sha256(canonical).hexdigest():
        raise ValueError("machine prefix proof internal SHA256 mismatch")
    required = ([f"{p}:default" for p in ("B1", "S1", "S2", "C70")] +
                [f"{p}:{s}" for p in ("B1", "S1", "S2", "C70")
                 for s in ("floor", "ceil")])
    if (proof.get("required_runs") != required
            or proof.get("trusted_prefix_proof_sha256") is not None
            or proof.get("trusted_pin_state") != "UNPINNED_AT_GENERATION"
            or not isinstance(proof.get("trusted_attestation_root_sha256"), str)
            or len(proof["trusted_attestation_root_sha256"]) != 64):
        raise ValueError("machine prefix proof run inventory or trust state is invalid")
    if (set(proof.get("baseline_runs", {})) != {"B1", "S1", "S2", "C70"}
            or set(proof.get("scenario_runs", {})) != {
                f"{p}:{s}" for p in ("B1", "S1", "S2", "C70")
                for s in ("floor", "ceil")}
            or proof.get("fee_knowledge") != {"PIT": "UNKNOWN",
                "source_availability": "UNKNOWN", "actual_broker_fees": "UNKNOWN"}):
        raise ValueError("machine prefix proof source inventory or fee unknowns are incomplete")
    comparisons = proof.get("comparisons", {})
    branches = {f"{p}:{s}" for p in ("B1", "S1", "S2", "C70")
                for s in ("floor", "ceil")}
    for branch in branches:
        files = comparisons.get(branch, {})
        if set(files) != {"execution_updates.jsonl", "daily_registry.jsonl",
                "strategy_decisions.jsonl", "registry_transitions.jsonl",
                "partial_account_states.jsonl"}:
            raise ValueError("machine prefix proof lacks a required ledger comparison")
        if any(item.get("raw_prefix_equal") is not True or item.get("differences")
               for item in files.values()):
            raise ValueError("machine prefix proof contains ledger differences")
