"""严格逐行比较前缀账本并从实际文件生成 verifier 记录。"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backtest.cnn_adapter.w1_prefix.fractional_prefix_gate import (
    BASE_HEAD,
    TRUSTED_PREFIX_ATTESTATOR_SHA256,
    TRUSTED_PREFIX_PROOF_SHA256,
)
from backtest.cnn_adapter.w1_prefix.prefix_attestor import _fixed_inputs, fixed_source_sha256

VERIFIER_VERSION = "prefix-ledger-verifier-v1"
PREFIX_CUTOFF = date(2021, 6, 7)
POLICIES = ("B1", "S1", "S2", "C70")
SCENARIOS = ("floor", "ceil")
BASELINE_ROOT = Path(
    "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_mechanical_results_20261028_v1")
PREFIX_OUTPUT_ROOT = Path(
    "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_w1_prefix_fix5_runs_20261028")
PREFIX_ATTESTATION_ROOT = Path(
    "C:/Users/yanwen/AppData/Local/Temp/opencode/staged_w1_prefix_fix5_attestation_20261028/attestation.json")
TRUSTED_PREFIX_ATTESTATION_SHA256: str | None = None
BASELINE_SOURCES_SHA256 = "08a33c4704a13b3c42e18b3fd4304705b44cb1c21bb8b79535332fc64c827cc9"
PREPARED_MANIFEST_SHA256 = "a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441"
PREREGISTRATION_SHA256 = "1dd0726fa1fb6f1f7cb86185fa14ac90e4f411b6deb9f47b6ae678a500c1f4ae"
BASELINE_AUDIT_SHA256 = {
    "B1": "ca6940c8a59f7d937c5899c683bae7d7a77e072a38a0d7e45d9d9c5d7b99c825",
    "S1": "ee9d77b8084705f0ec0345681e0fc9feb2809014fca18efe2bacc73ba90c870b",
    "S2": "14b86d3cb736bce6125c1eb30666482460d0ce9e7b6fa26a5a531806d72a9cd3",
    "C70": "0bcbf8e14d4c6796a3cf9df56542cb65dbc39a3f572a7450acb0de8776647299",
}
BASELINE_ARTIFACTS_SHA256 = {
    "B1": "24fab8f22125abbddb32ac4727f773a345fb1baf559448049eac97e0defe239d",
    "S1": "85c20e5e48be3c8ffcfcaf69fcc8990da216c28af5080739749d39aee22ec9ac",
    "S2": "3614f9946f6f6c70f4f6b2871a80a628f981069b0cd66c86b724a2ee16c704f1",
    "C70": "605233d1cdd02911079efa61dde0dba5bb58536e3c5e127687d9f1086a6cbb41",
}
ORIGINAL_CORE_SHA256 = "aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00"
NEW_CORE_SHA256 = "4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819"
ORIGINAL_CORE_PATH = Path(r"D:\code\cnn_full_20260905\cnn\.venv\Lib\site-packages\backtest_core\engine\account_runner.py")
ISOLATED_CORE_PATH = Path(r"C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src\backtest_core\engine\account_runner.py")
PREFIX_EXPERIMENT_ID = "w1_dual_core_cutoff_2021-06-07_v1"
BASELINE_LEDGER_SHA256 = {
    "B1": {"execution_updates.jsonl": "2b48390349337c4fbe10dc4066696f8f940a1e672d86d59a72e52cb2c54ddbd0", "daily_registry.jsonl": "bcd1ef678943303384b97517ee329230aaf245cf2a4d5f52b50647055f080b31", "strategy_decisions.jsonl": "c63af66626a56544b91b1f8cc08000928d05b7b2096cc9bb7b61fc249394464f", "registry_transitions.jsonl": "1643f45d1c331c603413aa3142f86d9d3488fb6108c32e4a0edda89f9e58b929", "partial_account_states.jsonl": "c7d3d7f5be81c3f79a62023c6fe93b2cbe895a3f92b2576fe4a98681f69d3aee"},
    "S1": {"execution_updates.jsonl": "6511592a6deb239f49ed6ff4ac2a1b8d4e4c9f064319d0996338e025f35492fd", "daily_registry.jsonl": "1fa19ff2a150b641027d55c6e296b424ef1e008dc431a70469e7af85ceb33866", "strategy_decisions.jsonl": "3ee8fc9d4d928ed67549688aea859ee6129bfabe1914d7fbb6ac6cb57e88880a", "registry_transitions.jsonl": "3a1b7f9450ff01afffef75617a320739f21298de0014388d5e4fe4d90c5813df", "partial_account_states.jsonl": "bb763b59364ee6c6f8b62bc193fb7a600e8d4730058fce94e362c476d64210ff"},
    "S2": {"execution_updates.jsonl": "f6d3434754b8d7d5e52e49a6b608a5ba6cc785a3863c7b39a1af6bae7068b2a7", "daily_registry.jsonl": "f4f7fa2a0bd74ebeb725ac5e43ebaf04fcca2b69f7a76a0e7c1536bb75c27faa", "strategy_decisions.jsonl": "302129d784e4966148612dbf4013e5ce39b87867c8f42288973596b52c1ecd79", "registry_transitions.jsonl": "edede9531304c16083e9944c4bcecf05675312cbc1ff9c207cf1aae7a3e6aab6", "partial_account_states.jsonl": "7fedec8b20f7279bb1a121c895befcf60b8bc209d6de098455ef9f179910ef01"},
    "C70": {"execution_updates.jsonl": "38394c475adfc1f343161cd7cc6f008e4d7f71f6de48e2865f66b976f7cdb0fa", "daily_registry.jsonl": "71cda44e5d11599450417ac9fdc9aef654415fd5ebc727c4bed4623fabd539b5", "strategy_decisions.jsonl": "9b4c06984bce90f2d28d8211278118b94ff37888006efa0d79ec0614ea35a9cb", "registry_transitions.jsonl": "e8629a31b60231870740ec4da36fea85a00118b95c71f112989fddba7141cce4", "partial_account_states.jsonl": "ddffe7873a0eb0925b1f6944c5aba675760921f803613c3af22f423cf4a2a9dd"},
}
W1_PREFIX_REQUIRED_LEDGERS = (
    "execution_updates.jsonl", "daily_registry.jsonl", "strategy_decisions.jsonl",
    "registry_transitions.jsonl", "partial_account_states.jsonl",
)
ACCESS_FILES = ("prefix_market_access.jsonl", "prefix_ranking_access.jsonl",
                "quantity_rule_usage.jsonl", "prefix_fee_policy.jsonl")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 对象含重复字段: {key!r}")
        result[key] = value
    return result


def _parse_lines(path: Path) -> list[tuple[bytes, Any]]:
    raw = path.read_bytes()
    lines = raw.splitlines()
    parsed: list[tuple[bytes, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise ValueError(f"{path}:{number}: JSONL 不允许空行")
        value = json.loads(line, object_pairs_hook=_pairs_without_duplicates)
        parsed.append((line, value))
    return parsed


def _pointer(path: str, key: str | int) -> str:
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{token}"


def _field_differences(left: Any, right: Any, path: str = "") -> list[dict[str, Any]]:
    if type(left) is not type(right):
        return [{"pointer": path or "/", "baseline": left, "replay": right}]
    if isinstance(left, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            child = _pointer(path, key)
            if key not in left or key not in right:
                differences.append({"pointer": child, "baseline_present": key in left,
                                    "replay_present": key in right,
                                    "baseline": left.get(key), "replay": right.get(key)})
            else:
                differences.extend(_field_differences(left[key], right[key], child))
        return differences
    if isinstance(left, list):
        differences = []
        for index in range(max(len(left), len(right))):
            if index >= len(left) or index >= len(right):
                differences.append({"pointer": _pointer(path, index),
                                    "baseline": left[index] if index < len(left) else None,
                                    "replay": right[index] if index < len(right) else None})
            else:
                differences.extend(_field_differences(left[index], right[index], _pointer(path, index)))
        return differences
    if left != right:
        return [{"pointer": path or "/", "baseline": left, "replay": right}]
    return []


def compare_jsonl(baseline_path: str | Path, replay_path: str | Path) -> dict[str, Any]:
    """比较原始文件字节和同序 JSON 行，返回字段差异与双方哈希。"""
    baseline = Path(baseline_path)
    replay = Path(replay_path)
    left, right = _parse_lines(baseline), _parse_lines(replay)
    differences: list[dict[str, Any]] = []
    for index in range(max(len(left), len(right))):
        if index >= len(left) or index >= len(right):
            differences.append({"line": index + 1, "kind": "missing_or_extra_row",
                                "baseline_present": index < len(left),
                                "replay_present": index < len(right)})
            continue
        raw_left, value_left = left[index]
        raw_right, value_right = right[index]
        fields = _field_differences(value_left, value_right)
        if raw_left != raw_right and not fields:
            fields.append({"pointer": "/$raw", "baseline": raw_left.hex(), "replay": raw_right.hex()})
        for field in fields:
            differences.append({"line": index + 1, **field})
    return {
        "baseline_sha256": _sha256(baseline), "replay_sha256": _sha256(replay),
        "baseline_rows": len(left), "replay_rows": len(right),
        "raw_bytes_equal": baseline.read_bytes() == replay.read_bytes(),
        "differences": differences,
    }


def verify_ledger_directories(
    baseline_dir: str | Path, replay_dir: str | Path, ledger_names: tuple[str, ...],
) -> dict[str, Any]:
    """按调用方指定账本名逐一比对；不排序行或压成集合。"""
    if (len(ledger_names) != len(W1_PREFIX_REQUIRED_LEDGERS)
            or set(ledger_names) != set(W1_PREFIX_REQUIRED_LEDGERS)):
        raise ValueError("W1 prefix 必须逐一比对固定的五类事件账本")
    baseline, replay = Path(baseline_dir), Path(replay_dir)
    if baseline.resolve() == replay.resolve():
        raise ValueError("baseline 与 replay 必须是独立目录")
    expected = set(ledger_names)
    actual_left = {p.name for p in baseline.iterdir() if p.is_file() and p.name.endswith(".jsonl")}
    actual_right = {p.name for p in replay.iterdir() if p.is_file() and p.name.endswith(".jsonl")}
    files = {name: compare_jsonl(baseline / name, replay / name)
             for name in ledger_names if (baseline / name).is_file() and (replay / name).is_file()}
    missing = sorted(expected - files.keys())
    exact_file_sets = actual_left == expected and actual_right == expected
    nonempty = not missing and all(
        row["baseline_rows"] > 0 and row["replay_rows"] > 0 for row in files.values())
    rows_identical = exact_file_sets and nonempty and all(
        row["raw_bytes_equal"] and not row["differences"] for row in files.values())
    return {"rows_identical": rows_identical, "exact_file_sets": exact_file_sets,
            "all_nonempty": nonempty, "missing_ledgers": missing,
            "unexpected_baseline": sorted(actual_left - expected),
            "unexpected_replay": sorted(actual_right - expected), "files": files}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs_without_duplicates)
    if not isinstance(value, dict):
        raise TypeError(f"{path}: expected JSON object")
    return value


def _verify_run_artifacts(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = _read_json(directory / "attempt_audit.json")
    artifacts = _read_json(directory / "artifacts.json")
    if not artifacts:
        raise ValueError(f"{directory}: artifacts manifest is empty")
    for name, expected in artifacts.items():
        path = directory / name
        if Path(name).name != name or not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"{directory}: artifact mismatch {name}")
    return audit, artifacts


def _is_readonly(path: Path) -> bool:
    return not bool(path.stat().st_mode & stat.S_IWRITE)


def _verify_external_attestation(branch: str, directory: Path,
                                 identity: Mapping[str, Any]) -> dict[str, Any]:
    if TRUSTED_PREFIX_ATTESTATION_SHA256 is None:
        raise ValueError("external attestation root is not independently pinned")
    root = PREFIX_ATTESTATION_ROOT.resolve()
    if root.is_relative_to(PREFIX_OUTPUT_ROOT.resolve()) or not root.is_file():
        raise ValueError("external attestation root is absent or inside runner output")
    if _sha256(root) != TRUSTED_PREFIX_ATTESTATION_SHA256:
        raise ValueError("external attestation root SHA mismatch")
    if TRUSTED_PREFIX_ATTESTATOR_SHA256 is None:
        raise ValueError("external attestor source is not independently pinned")
    attestor_path = Path(__file__).with_name("prefix_attestor.py")
    if _sha256(attestor_path) != TRUSTED_PREFIX_ATTESTATOR_SHA256:
        raise ValueError("external attestor executable SHA mismatch")
    if not _is_readonly(root):
        raise ValueError("external attestation root is not read-only")
    record = _read_json(root)
    if record.get("schema_version") != "w1_prefix_external_attestation_v1":
        raise ValueError("external attestation schema mismatch")
    experiment_identity = record.get("prefix_experiment_identity")
    if not isinstance(experiment_identity, dict):
        raise TypeError("external attestation lacks the dual-core experiment identity")
    if (record.get("status") != "PINNED"
            or record.get("attestor_sha256") != TRUSTED_PREFIX_ATTESTATOR_SHA256
            or record.get("trusted_attestor_sha256") != TRUSTED_PREFIX_ATTESTATOR_SHA256):
        raise ValueError("external attestor pin is absent or mismatched")
    if record.get("source_sha256") != fixed_source_sha256():
        raise ValueError("external attestation source inventory differs from fixed pins")
    output = record.get("branches", {}).get(branch, {})
    if Path(output.get("path", "")).resolve() != directory.resolve():
        raise ValueError("external attestation branch path mismatch")
    entries = sorted(directory.rglob("*"))
    if any(path.is_symlink() for path in entries):
        raise ValueError("external attestation output contains a symlink")
    current_files = {path.relative_to(directory).as_posix(): _sha256(path)
        for path in entries if path.is_file()}
    if output.get("files") != current_files:
        raise ValueError("external attestation output hashes mismatch")
    if _read_json(directory / "prefix_experiment.json") != experiment_identity:
        raise ValueError("branch prefix experiment identity differs from external attestation")
    for raw_path, digest in record.get("source_sha256", {}).items():
        path = Path(raw_path)
        if not path.is_file() or _sha256(path) != digest:
            raise ValueError("external attestation source SHA mismatch")
    inputs = record.get("input_sha256", {})
    fixed_inputs = _fixed_inputs({"prepared_manifest_path": record.get("prepared_manifest_path"),
        "input_config_path": record.get("input_config_path"),
        "official_pdf_path": record.get("official_pdf_path"), "inputs": inputs})
    if fixed_inputs != inputs:
        raise ValueError("external attestation input map differs from fixed v12 sources")
    expected_inputs = {
        str(Path(identity["prepared_manifest_path"]).resolve()): PREPARED_MANIFEST_SHA256,
        str(Path(identity["preregistration_path"]).resolve()): PREREGISTRATION_SHA256,
        str(Path(identity["signal_path"]).resolve()): identity["signal_sha256"],
    }
    if not record.get("source_sha256") or any(inputs.get(path) != digest
            for path, digest in expected_inputs.items()):
        raise ValueError("external attestation fixed input inventory mismatch")
    for raw_path, digest in expected_inputs.items():
        if not Path(raw_path).is_file() or _sha256(Path(raw_path)) != digest:
            raise ValueError("external attestation fixed input SHA mismatch")
    access = record.get("read_only_access_records", {}).get(branch, {})
    for name in ("prefix_market_access.jsonl", "prefix_ranking_access.jsonl",
                 "quantity_rule_usage.jsonl", "prefix_fee_policy.jsonl"):
        item = access.get(name, {})
        path = Path(item.get("external_path", ""))
        if (path.resolve().is_relative_to(PREFIX_OUTPUT_ROOT.resolve())
                or not path.is_file() or not _is_readonly(path)
                or current_files.get(name) != item.get("sha256")
                or _sha256(path) != item.get("sha256")):
            raise ValueError(f"external read-only access record invalid: {name}")
    return {"attestation_root_sha256": TRUSTED_PREFIX_ATTESTATION_SHA256,
            "plan_sha256": record["plan_sha256"], "branch": branch,
            "prefix_experiment_identity": experiment_identity,
            "output_sha256": _canonical_sha(current_files)}


def _prefix_records(path: Path, *,
                    allow_post_cutoff: bool = False) -> list[tuple[bytes, dict[str, Any]]]:
    day_fields = ("trading_date", "signal_date", "date")
    rows = []
    last_day = None
    for raw, value in _parse_lines(path):
        if not isinstance(value, dict):
            raise TypeError(f"{path}: ledger row must be an object")
        raw_day = next((value[key] for key in day_fields if key in value), None)
        if not isinstance(raw_day, str):
            raise TypeError(f"{path}: missing ISO date field")
        day = date.fromisoformat(raw_day[:10])
        if last_day is not None and day < last_day:
            raise ValueError(f"{path}: ledger date order regressed")
        if day > PREFIX_CUTOFF and not allow_post_cutoff:
            raise ValueError(f"{path}: ledger row is after cutoff {PREFIX_CUTOFF}")
        last_day = day
        if day <= PREFIX_CUTOFF:
            rows.append((raw, value))
    if not rows:
        raise ValueError(f"{path}: empty prefix through {PREFIX_CUTOFF}")
    return rows


def _baseline_identity(policy: str, directory: Path) -> dict[str, Any]:
    expected_dir = (BASELINE_ROOT / f"W1_{policy}").resolve()
    if directory.resolve() != expected_dir:
        raise ValueError("baseline path is not the controlled original W1 directory")
    if _sha256(directory / "attempt_audit.json") != BASELINE_AUDIT_SHA256[policy]:
        raise ValueError("original baseline attempt audit pin mismatch")
    if _sha256(directory / "artifacts.json") != BASELINE_ARTIFACTS_SHA256[policy]:
        raise ValueError("original baseline artifacts manifest pin mismatch")
    audit, artifacts = _verify_run_artifacts(directory)
    sources_path = directory / "sources_manifest.json"
    sources = _read_json(sources_path)
    if _sha256(sources_path) != BASELINE_SOURCES_SHA256:
        raise ValueError("original baseline sources manifest SHA mismatch")
    if sources.get("core_sha256") != ORIGINAL_CORE_SHA256:
        raise ValueError("original baseline wheel identity mismatch")
    config = audit.get("config", {})
    if config.get("period_id") != "W1" or config.get("policy") != policy:
        raise ValueError("original baseline strategy identity mismatch")
    calendar = audit.get("window", {}).get("execution_calendar", [])
    if PREFIX_CUTOFF.isoformat() not in calendar or calendar != sorted(set(calendar)):
        raise ValueError("original baseline calendar lacks ordered cutoff")
    failure = audit.get("error", {}).get("reason", "")
    if (audit.get("mechanical_status") != "INCOMPLETE"
            or "dividend:27726:" not in failure
            or "noninteger_or_unrepresentable_share_quantity" not in failure):
        raise ValueError("original baseline is not the pinned post-cutoff CA interruption")
    for name, digest in BASELINE_LEDGER_SHA256[policy].items():
        if artifacts.get(name) != digest or _sha256(directory / name) != digest:
            raise ValueError(f"original baseline ledger pin mismatch: {policy}/{name}")
    signal_paths = sorted(path for path, digest in sources.get("artifacts", {}).items()
                          if digest == config.get("signal_file_sha256")
                          and (path.endswith("signal_W1.parquet") or
                               path.endswith("W1_F4_full_CPU_v1\\signals.parquet")))
    return {"audit": audit, "artifacts": artifacts,
            "sources_manifest_sha256": BASELINE_SOURCES_SHA256,
            "sources_artifacts_sha256": _sha256(sources_path),
            "signal_paths": signal_paths}


def _verify_dual_core_identity(directory: Path, identity: Mapping[str, Any],
                              attested: Mapping[str, Any]) -> dict[str, Any]:
    experiment = _read_json(directory / "prefix_experiment.json")
    if experiment != attested:
        raise ValueError("scenario dual-core identity differs from external attestation")
    digest = experiment.get("experiment_config_sha256")
    body = {key: value for key, value in experiment.items() if key != "experiment_config_sha256"}
    if digest != _canonical_sha(body):
        raise ValueError("dual-core experiment configuration SHA mismatch")
    if (experiment.get("schema_version") != "w1_dual_core_prefix_identity_v1"
            or experiment.get("experiment_id") != PREFIX_EXPERIMENT_ID
            or experiment.get("cutoff") != PREFIX_CUTOFF.isoformat()
            or experiment.get("prepared_manifest_sha256") != PREPARED_MANIFEST_SHA256
            or experiment.get("prepared_core_path") != str(ORIGINAL_CORE_PATH.resolve())
            or experiment.get("prepared_core_sha256") != ORIGINAL_CORE_SHA256
            or experiment.get("pit") != "UNKNOWN"
            or experiment.get("actual_after_tax_target_eligible") is not False):
        raise ValueError("dual-core experiment identity violates fixed v12 contract")
    runtime = (Path(str(experiment.get("runtime_core_path", ""))).resolve(),
               experiment.get("runtime_core_sha256"))
    allowed = {(ORIGINAL_CORE_PATH.resolve(), ORIGINAL_CORE_SHA256),
               (ISOLATED_CORE_PATH.resolve(), NEW_CORE_SHA256)}
    if runtime not in allowed or experiment.get("runtime_import_path") != str(runtime[0]):
        raise ValueError("runtime core path/SHA is outside the fixed dual-core allowlist")
    if not runtime[0].is_file() or _sha256(runtime[0]) != runtime[1]:
        raise ValueError("runtime import path bytes differ from recorded core identity")
    for key, value in (("prefix_experiment_id", PREFIX_EXPERIMENT_ID),
        ("prepared_core_path", experiment["prepared_core_path"]),
        ("prepared_core_sha256", ORIGINAL_CORE_SHA256),
        ("runtime_core_path", str(runtime[0])), ("runtime_core_sha256", runtime[1]),
        ("experiment_config_sha256", digest)):
        if identity.get(key) != value:
            raise ValueError(f"controlled run identity mismatch: {key}")
    if (identity.get("core_path") != str(runtime[0])
            or identity.get("core_sha256") != runtime[1]):
        raise ValueError("legacy runtime identity fields cannot replace dual-core fields")
    if (experiment.get("prepared_manifest_path") != identity.get("prepared_manifest_path")
            or experiment.get("prepared_manifest_sha256") != identity.get("prepared_manifest_sha256")):
        raise ValueError("prepared manifest identity differs between audit and experiment config")
    return experiment


def _scenario_identity(policy: str, scenario: str, directory: Path) -> dict[str, Any]:
    expected_dir = (PREFIX_OUTPUT_ROOT / f"W1_{policy}_{scenario}").resolve()
    if directory.resolve() != expected_dir:
        raise ValueError("scenario path is not its controlled branch output directory")
    raw_audit = _read_json(directory / "attempt_audit.json")
    identity = raw_audit.get("controlled_run_identity", {})
    attestation = _verify_external_attestation(
        f"W1_{policy}_{scenario}", directory, identity)
    _verify_dual_core_identity(directory, identity,
        attestation["prefix_experiment_identity"])
    audit, artifacts = _verify_run_artifacts(directory)
    if (identity.get("output_dir") != str(expected_dir) or
            identity.get("branch") != f"W1_{policy}_{scenario}" or
            identity.get("policy") != policy or identity.get("scenario") != scenario):
        raise ValueError("scenario controlled run identity mismatch")
    if identity.get("cutoff") != PREFIX_CUTOFF.isoformat():
        raise ValueError("scenario prefix cutoff mismatch")
    try:
        created_at = datetime.fromisoformat(identity.get("created_at_utc", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("scenario timestamp is invalid") from error
    if created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ValueError("scenario timestamp is not UTC")
    if identity.get("period_id") != "W1":
        raise ValueError("scenario period must be real W1, not a mini")
    for key in ("prepared_manifest_sha256", "signal_sha256", "signal_content_sha256",
                "checkpoint_sha256", "calendar_sha256", "universe_sha256", "scope_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(identity.get(key, ""))):
            raise ValueError(f"scenario identity lacks {key}")
    if audit.get("mechanical_status") != "PASS":
        raise ValueError("scenario run did not complete mechanically")
    prepared_path = Path(identity.get("prepared_manifest_path", ""))
    prereg_path = Path(identity.get("preregistration_path", ""))
    signal_path = Path(identity.get("signal_path", ""))
    if (not prepared_path.is_file() or _sha256(prepared_path) != PREPARED_MANIFEST_SHA256
            or identity.get("prepared_manifest_sha256") != PREPARED_MANIFEST_SHA256):
        raise ValueError("scenario prepared manifest is not the frozen v12 source")
    if (not prereg_path.is_file() or _sha256(prereg_path) != PREREGISTRATION_SHA256
            or identity.get("preregistration_sha256") != PREREGISTRATION_SHA256):
        raise ValueError("scenario pre-registration source mismatch")
    if not signal_path.is_file() or _sha256(signal_path) != identity.get("signal_sha256"):
        raise ValueError("scenario signal input bytes mismatch")
    _verify_signal_universe(audit, identity)
    evidence = _read_json(directory / "corporate_action_evidence.json")
    event = evidence.get("fractional_scenario", {})
    if event.get("scenario") != scenario or event.get("event_id") != "dividend:27726:5fb6350a1b1fc81990ef44c205be00cdbec5f3d76841eacebad0ecbb26194462":
        raise ValueError("scenario corporate-action branch identity mismatch")
    fee_evidence = _verify_cutoff_fee_record(directory, identity)
    return {"audit": audit, "identity": identity, "artifacts": artifacts,
            "dual_core_identity": _read_json(directory / "prefix_experiment.json"),
            "external_attestation": attestation,
            "fee_evidence": fee_evidence}


def _assert_access_cutoff(directory: Path) -> None:
    checks = (("prefix_market_access.jsonl", "end"),
              ("prefix_ranking_access.jsonl", "trading_date"),
              ("quantity_rule_usage.jsonl", "rule_lookup_date"))
    for filename, field in checks:
        for _raw, row in _parse_lines(directory / filename):
            if date.fromisoformat(str(row[field])[:10]) > PREFIX_CUTOFF:
                raise ValueError(f"future information access in {filename}")


def _compare_prefix_files(baseline: Path, scenario: Path) -> dict[str, Any]:
    left, right = _prefix_records(baseline, allow_post_cutoff=True), _prefix_records(scenario)
    differences = []
    for index in range(max(len(left), len(right))):
        if index >= len(left) or index >= len(right):
            differences.append({"line": index + 1, "kind": "missing_or_extra_row",
                "baseline_present": index < len(left), "scenario_present": index < len(right)})
        elif left[index][0] != right[index][0]:
            differences.append({"line": index + 1, "baseline_raw": left[index][0].hex(),
                                "scenario_raw": right[index][0].hex()})
    raw_left = b"\n".join(row for row, _ in left) + b"\n"
    raw_right = b"\n".join(row for row, _ in right) + b"\n"
    return {"baseline_rows": len(left), "scenario_rows": len(right),
        "baseline_prefix_sha256": hashlib.sha256(raw_left).hexdigest(),
        "scenario_prefix_sha256": hashlib.sha256(raw_right).hexdigest(),
        "raw_prefix_equal": raw_left == raw_right, "differences": differences}


def _build_machine_proof(baseline_root: Path, scenario_root: Path,
                         generated_at_utc: str) -> dict[str, Any]:
    if baseline_root.resolve() != BASELINE_ROOT.resolve():
        raise ValueError("refusing non-controlled baseline root")
    if scenario_root.resolve() != PREFIX_OUTPUT_ROOT.resolve():
        raise ValueError("refusing non-controlled scenario root")
    base_path, scenario_path = baseline_root.resolve(), scenario_root.resolve()
    if (base_path == scenario_path or base_path in scenario_path.parents
            or scenario_path in base_path.parents):
        raise ValueError("baseline and scenario roots must be independent")
    baseline_runs = {}
    comparisons = {}
    expected_configs = {}
    expected_signal_paths = {}
    for policy in POLICIES:
        directory = baseline_root / f"W1_{policy}"
        baseline = _baseline_identity(policy, directory)
        baseline_runs[policy] = {"path": str(directory.resolve()),
            "sources_manifest_sha256": baseline["sources_manifest_sha256"],
            "attempt_audit_sha256": _sha256(directory / "attempt_audit.json"),
            "artifacts_manifest_sha256": _sha256(directory / "artifacts.json"),
            "signal_source_paths": baseline["signal_paths"],
            "ledger_sha256": {name: baseline["artifacts"][name]
                              for name in W1_PREFIX_REQUIRED_LEDGERS}}
        expected_configs[policy] = baseline["audit"]["config"]
        expected_signal_paths[policy] = {str(Path(path).resolve())
                                         for path in baseline["signal_paths"]}
    scenario_runs = {}
    prepared_hashes = set()
    dual_core_identities = {}
    shared_inputs = set()
    policy_scopes: dict[str, set[str]] = {policy: set() for policy in POLICIES}
    for policy in POLICIES:
        for scenario in SCENARIOS:
            branch = f"{policy}:{scenario}"
            directory = scenario_root / f"W1_{policy}_{scenario}"
            run = _scenario_identity(policy, scenario, directory)
            identity, audit = run["identity"], run["audit"]
            experiment = run["dual_core_identity"]
            dual_core_identities[_canonical_sha(experiment)] = experiment
            if str(Path(identity["signal_path"]).resolve()) not in expected_signal_paths[policy]:
                raise ValueError(f"{branch}: signal path is not in the pinned original source manifest")
            if audit.get("config") != expected_configs[policy]:
                raise ValueError(f"{branch}: independent strategy config mismatch")
            if identity.get("config_sha256") != _canonical_sha(expected_configs[policy]):
                raise ValueError(f"{branch}: config hash mismatch")
            if identity.get("signal_sha256") != expected_configs[policy].get("signal_file_sha256"):
                raise ValueError(f"{branch}: signal source mismatch")
            if identity.get("checkpoint_sha256") != expected_configs[policy].get("checkpoint_sha256"):
                raise ValueError(f"{branch}: checkpoint source mismatch")
            expected_scope = _canonical_sha({"source_id": expected_configs[policy]["source_id"],
                "checkpoint_sha256": identity["checkpoint_sha256"],
                "signal_sha256": identity["signal_sha256"], "policy": policy})
            if identity.get("scope_sha256") != expected_scope:
                raise ValueError(f"{branch}: scope hash mismatch")
            shared_inputs.add(_canonical_sha({key: identity[key] for key in (
                "signal_sha256", "signal_content_sha256", "checkpoint_sha256",
                "prepared_manifest_sha256", "preregistration_sha256",
                "calendar_sha256", "universe_sha256", "prepared_core_sha256",
                "runtime_core_path", "runtime_core_sha256", "experiment_config_sha256")}))
            policy_scopes[policy].add(identity["scope_sha256"])
            prepared_hashes.add(identity["prepared_manifest_sha256"])
            _assert_access_cutoff(directory)
            branch_comparisons = {}
            for name in W1_PREFIX_REQUIRED_LEDGERS:
                branch_comparisons[name] = _compare_prefix_files(
                    baseline_root / f"W1_{policy}" / name, directory / name)
            comparisons[branch] = branch_comparisons
            scenario_runs[branch] = {"path": str(directory.resolve()),
                "identity_sha256": _canonical_sha(identity),
                "artifacts_manifest_sha256": _sha256(directory / "artifacts.json"),
                "external_attestation": run["external_attestation"],
                "fee_evidence": run["fee_evidence"], "config_sha256": identity["config_sha256"]}
    if len(prepared_hashes) != 1:
        raise ValueError("the eight scenario branches do not share one frozen prepared manifest")
    if len(dual_core_identities) != 1:
        raise ValueError("the eight branches do not share one dual-core experiment identity")
    if len(shared_inputs) != 1 or any(len(values) != 1 for values in policy_scopes.values()):
        raise ValueError("the eight branches do not share frozen signal/calendar/universe scope")
    output_paths = {Path(row["path"]).resolve() for row in baseline_runs.values()}
    output_paths.update(Path(row["path"]).resolve() for row in scenario_runs.values())
    if len(output_paths) != 12:
        raise ValueError("the 12 required branch directories are not distinct")
    match = all(result["raw_prefix_equal"] for run in comparisons.values()
                for result in run.values())
    body = {"schema_version": "w1_prefix_machine_proof_v1",
        "status": "PASS" if match else "FAIL", "base_head": BASE_HEAD,
        "through_date": PREFIX_CUTOFF.isoformat(),
        "canonical_prefix_match": match, "floor_ceil_prefix_match": match,
        "trusted_prefix_proof_sha256": TRUSTED_PREFIX_PROOF_SHA256,
        "trusted_attestation_root_sha256": TRUSTED_PREFIX_ATTESTATION_SHA256,
        "trusted_pin_state": "UNPINNED_AT_GENERATION",
        "generated_at_utc": generated_at_utc,
        "generator_sha256": _sha256(Path(__file__).resolve()),
        "baseline_root": str(baseline_root.resolve()),
        "scenario_root": str(scenario_root.resolve()),
        "prepared_manifest_sha256": next(iter(prepared_hashes)),
        "dual_core_identity": next(iter(dual_core_identities.values())),
        "required_runs": [f"{p}:default" for p in POLICIES] +
                         [f"{p}:{s}" for p in POLICIES for s in SCENARIOS],
        "baseline_runs": baseline_runs, "scenario_runs": scenario_runs,
        "comparisons": comparisons,
        "fee_knowledge": {"PIT": "UNKNOWN", "source_availability": "UNKNOWN",
                          "actual_broker_fees": "UNKNOWN"}}
    body["proof_sha256"] = _canonical_sha(body)
    return body


def generate_prefix_proof(output_path: str | Path, *,
                          baseline_root: str | Path | None = None,
                          scenario_root: str | Path | None = None) -> str:
    """从固定原始4基线与受控8分支真实目录生成机器候选 proof。"""
    target = Path(output_path)
    if target.exists():
        raise FileExistsError(f"拒绝覆盖 prefix proof: {target}")
    baseline = Path(baseline_root) if baseline_root is not None else BASELINE_ROOT
    scenarios = Path(scenario_root) if scenario_root is not None else PREFIX_OUTPUT_ROOT
    if (target.resolve().is_relative_to(baseline.resolve())
            or target.resolve().is_relative_to(scenarios.resolve())):
        raise ValueError("prefix proof output must be outside controlled run directories")
    proof = _build_machine_proof(baseline, scenarios, datetime.now(UTC).isoformat())
    encoded = json.dumps(proof, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8") + b"\n"
    with target.open("xb") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def verify_machine_prefix_proof(path: str | Path) -> dict[str, Any]:
    """从 proof 声明的固定目录重建证据；不接受文件内自报的 PASS。"""
    proof_path = Path(path)
    proof = _read_json(proof_path)
    supplied_sha = proof.pop("proof_sha256", None)
    if supplied_sha != _canonical_sha(proof):
        raise ValueError("machine proof SHA256 mismatch")
    rebuilt = _build_machine_proof(Path(proof["baseline_root"]),
        Path(proof["scenario_root"]), proof["generated_at_utc"])
    if {key: value for key, value in rebuilt.items() if key != "proof_sha256"} != proof:
        raise ValueError("machine proof does not match current controlled run outputs")
    if rebuilt["trusted_prefix_proof_sha256"] is not None:
        raise ValueError("trusted pin must remain unset until independent review")
    return rebuilt


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _verify_cutoff_fee_record(directory: Path, identity: Mapping[str, Any]) -> dict[str, Any]:
    lines = _parse_lines(directory / "prefix_fee_policy.jsonl")
    if len(lines) != 1:
        raise ValueError("prefix must contain one cutoff fee policy record")
    bundle = lines[0][1].get("cutoff_fee_bundle", {})
    if bundle.get("schema_version") != "cutoff_fee_bundle_v2":
        raise ValueError("unsupported cutoff fee bundle schema")
    try:
        generated = datetime.fromisoformat(bundle.get("generated_at_utc", ""))
    except (TypeError, ValueError) as error:
        raise ValueError("cutoff fee generation timestamp is invalid") from error
    if generated.utcoffset() != UTC.utcoffset(generated):
        raise ValueError("cutoff fee timestamp is not UTC")
    if set(bundle.get("markets", {})) != {"SSE_A", "SZSE_A"}:
        raise ValueError("cutoff fee bundle must bind both A-share markets")
    payload = {key: value for key, value in bundle.items() if key != "sha256"}
    if bundle.get("sha256") != _canonical_sha(payload):
        raise ValueError("cutoff fee bundle integrity mismatch")
    unknown = {"pit_evidence": "UNKNOWN", "source_availability": "UNKNOWN",
               "actual_broker_fees": "UNKNOWN"}
    if bundle.get("knowledge") != unknown:
        raise ValueError("cutoff fee knowledge must remain UNKNOWN")
    if (bundle.get("information_cutoff") != PREFIX_CUTOFF.isoformat()
            or bundle.get("preregistration_sha256") != identity.get("preregistration_sha256")
            or bundle.get("scope_sha256") != identity.get("scope_sha256")
            or bundle.get("calendar_sha256") != identity.get("calendar_sha256")
            or bundle.get("universe_sha256") != identity.get("universe_sha256")):
        raise ValueError("cutoff fee bundle scope/source identity mismatch")
    source = bundle.get("resolver_source", {})
    source_path = Path(source.get("path", ""))
    if (source_path.name != "historical_costs.py" or not source_path.is_file()
            or _sha256(source_path) != source.get("sha256")):
        raise ValueError("cutoff fee resolver source mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", str(bundle.get("preregistration_sha256"))):
        raise ValueError("cutoff fee bundle lacks a registered preregistration hash")
    return {"bundle_sha256": bundle["sha256"], "resolver_sha256": source["sha256"],
            "preregistration_sha256": bundle["preregistration_sha256"],
            "scope_sha256": bundle["scope_sha256"],
            "calendar_sha256": bundle["calendar_sha256"],
            "universe_sha256": bundle["universe_sha256"], "knowledge": unknown}


def _verify_signal_universe(audit: Mapping[str, Any], identity: Mapping[str, Any]) -> None:
    from backtest.cnn_adapter.staged_candidate_runner import (
        _signal_content_fingerprint,
        load_frozen_signal_parquet,
    )
    signal_path = Path(identity["signal_path"])
    rows, actual_sha = load_frozen_signal_parquet(signal_path, identity["signal_sha256"])
    if _signal_content_fingerprint(rows) != identity.get("signal_content_sha256"):
        raise ValueError("scenario signal content fingerprint mismatch")
    codes = sorted({str(row["instrument_id"]) for day_rows in rows.values() for row in day_rows})
    if codes != identity.get("universe_codes") or _canonical_sha(codes) != identity.get("universe_sha256"):
        raise ValueError("scenario signal universe hash mismatch")
    window = audit.get("window", {})
    calendar = window.get("execution_calendar", [])
    if _canonical_sha(calendar) != identity.get("calendar_sha256"):
        raise ValueError("scenario calendar hash mismatch")
    anchor, end = date.fromisoformat(window["anchor_date"]), date.fromisoformat(window["evaluation_end"])
    expected_days = {date.fromisoformat(day) for day in calendar
                     if anchor < date.fromisoformat(day) <= end}
    if set(rows) != expected_days:
        raise ValueError("scenario signal dates differ from the frozen W1 calendar")
    if actual_sha != identity.get("signal_sha256"):
        raise ValueError("scenario signal SHA mismatch")


def write_blocked_prefix_record(path: str | Path) -> str:
    """只写 gate schema 的 BLOCKED 记录，绝不从调用者输入接受 PASS。"""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"拒绝覆盖 prefix 记录: {target}")
    record = {
        "status": "BLOCKED", "base_head": BASE_HEAD, "through_date": "2021-06-07",
        "canonical_prefix_match": False, "floor_ceil_prefix_match": False,
        "trusted_prefix_proof_sha256": TRUSTED_PREFIX_PROOF_SHA256,
        "required_runs": [f"{strategy}:{path}" for strategy in ("B1", "S1", "S2", "C70")
                          for path in ("default", "floor", "ceil")],
        "blockers": ["source identities and original baseline hashes not independently bound",
                     "12 real runs and three-way canonical comparison not executed"],
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with target.open("xb") as stream:
        stream.write(encoded)
    return hashlib.sha256(encoded).hexdigest()
