"""由 runner 外的独立进程固定输入、源码、输出与访问记录摘要。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import date
from pathlib import Path
from typing import Any

from .fractional_prefix_gate import TRUSTED_PREFIX_ATTESTATOR_SHA256

ATTESTATION_SCHEMA = "w1_prefix_external_attestation_v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE = Path(r"C:\Users\yanwen\AppData\Local\Temp\opencode\backtest-core-w1-stop-20261028\src\backtest_core\engine\account_runner.py")
PREPARED_MANIFEST_SHA256 = "a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441"
OFFICIAL_PDF_SHA256 = "c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd"
ACCESS_FILES = ("prefix_market_access.jsonl", "prefix_ranking_access.jsonl",
                "quantity_rule_usage.jsonl", "prefix_fee_policy.jsonl")


def fixed_source_sha256() -> dict[str, str]:
    """返回代码审阅冻结的 runner/core 源码 SHA 清单。"""
    relative = ("staged_candidate_runner.py", "staged_production_inputs.py",
        "fractional_scenarios.py", "fractional_scenario_cli.py",
        "prefix_ledger_verifier.py", "historical_costs.py",
        "corporate_action_context.py", "corporate_action_snapshot_loader.py",
        "quantity_rules.py", "staged_allocation.py", "staged_order_strategy.py",
        "staged_execution_bridge.py", "raw_market_provider.py", "raw_market_inputs.py")
    hashes = (
        "37fcf150a0c3646b44afbfe1d3c9ae2bd1e0cac7067779e4c0e050c2081bf54b",
        "cef7b7bb2b7e21ce31f58929a07f2531e6f5e25aa5b6239475d45f05d0675f84",
        "7112bedef9a10d802e58f18580e391e25355803c838b401c215941cb9ce37180",
        "4e6246dbdd56bf5da6edebb88ac87c45dfa692de45b04e6a1c177e63e709a46f",
        "92c842a375b5e719761df8144dc686b27455c491aeed2a1f3811c3fb6c32145a",
        "aca04da66bebfe34765bb166639a5f88bfed215d7343e142fe306ed0567af329",
        "8c88683136972e032dc37c11d96c3eff4d04c34c508fe9a2545c823a1aa22510",
        "31f72bec1f2adecd7e7914c191e2f442515544dd9eda802df928fb77c405dd49",
        "d88ed93ab5e41b698f1765bce37571f60707989d7ea2c4a7377340960f3dba8c",
        "c4bd8a85f6ab3564efd8f8b5c4d6daeaccb7277e1ee81deec8eef6d69d22a314",
        "9c87f2e1de903f18748f98d4d55f368e415f4c797b8f7be9d3733c20e595b015",
        "37d65236b2d2ee55884f2126826ab77eff13009021fc1c8985498ca44d611e63",
        "53ce8d8e99c1705e54f571846c4a93fc3fb867f18991973854f0f172514d582e",
        "000c382d56bf6e9737677314d728d7306348d252189815896b9ec5be4f3bb920",
    )
    result = {str((REPO_ROOT / "backtest/cnn_adapter" / name).resolve()): digest
              for name, digest in zip(relative, hashes, strict=True)}
    result[str(CORE_SOURCE.resolve())] = "4d3a28c46b38664d1ed86013ee44319ab77a522ec33477575b571fc2220a1819"
    return result


def _validate_prefix_experiment_identity(experiment: dict[str, Any]) -> dict[str, Any]:
    """要求双 core 身份的关键字段齐全，缺失时保持 fail closed。"""
    required = ("experiment_id", "prepared_manifest_sha256", "prepared_core_path",
        "prepared_core_sha256", "runtime_core_path", "runtime_core_sha256",
        "experiment_config_sha256")
    if any(not experiment.get(key) for key in required):
        raise ValueError("attestor prefix experiment identity is incomplete")
    return experiment


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _file_map(root: Path) -> dict[str, str]:
    entries = sorted(root.rglob("*"))
    if any(item.is_symlink() for item in entries):
        raise ValueError(f"attestor refuses symlink output: {root}")
    return {item.relative_to(root).as_posix(): _sha(item)
            for item in entries if item.is_file()}


def _check_fixed_paths(entries: dict[str, str], label: str) -> dict[str, str]:
    result = {}
    for raw_path, expected in entries.items():
        path = Path(raw_path).resolve()
        if len(expected) != 64 or not path.is_file() or _sha(path) != expected:
            raise ValueError(f"{label} fixed SHA mismatch: {path}")
        result[str(path)] = expected
    return result


def _fixed_inputs(plan: dict[str, Any]) -> dict[str, str]:
    prepared_path = Path(plan["prepared_manifest_path"]).resolve()
    config_path = Path(plan["input_config_path"]).resolve()
    pdf_path = Path(plan["official_pdf_path"]).resolve()
    if not prepared_path.is_file() or _sha(prepared_path) != PREPARED_MANIFEST_SHA256:
        raise ValueError("attestor requires the frozen v12 prepared manifest SHA")
    manifest_sidecar = prepared_path.with_suffix(".sha256")
    if manifest_sidecar.read_bytes() != PREPARED_MANIFEST_SHA256.encode("ascii"):
        raise ValueError("attestor requires the exact frozen manifest sidecar bytes")
    prepared = _read(prepared_path)
    if not config_path.is_file() or _read(config_path) != prepared.get("config"):
        raise ValueError("attestor input config differs from the frozen prepared manifest")
    if not pdf_path.is_file() or _sha(pdf_path) != OFFICIAL_PDF_SHA256:
        raise ValueError("attestor official PDF SHA mismatch")
    expected = {str(Path(path).resolve()): digest
                for path, digest in prepared.get("artifacts", {}).items()}
    expected[str(prepared_path)] = PREPARED_MANIFEST_SHA256
    expected[str(manifest_sidecar)] = _sha(manifest_sidecar)
    expected[str(config_path)] = _sha(config_path)
    expected[str(pdf_path)] = OFFICIAL_PDF_SHA256
    declared = {str(Path(path).resolve()): digest
                for path, digest in plan.get("inputs", {}).items()}
    if declared != expected:
        raise ValueError("attestor input inventory differs from pinned prepared artifacts")
    return _check_fixed_paths(declared, "input")


def _access_record(path: Path, cutoff: date) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    date_fields = ("end", "trading_date", "rule_lookup_date", "information_cutoff")
    for row in rows:
        for field in date_fields:
            if field in row and date.fromisoformat(str(row[field])[:10]) > cutoff:
                raise ValueError(f"future access record: {path}/{field}")
    return {"sha256": _sha(path), "records": len(rows), "read_only": True}


def attest_prefix_outputs(plan_path: str | Path, attestation_path: str | Path) -> str:
    """从外部固定计划核对八个输出，并把访问记录复制到只读根目录。"""
    plan_file, target = Path(plan_path).resolve(), Path(attestation_path).resolve()
    plan = _read(plan_file)
    schema = plan.get("schema_version")
    if schema not in ("w1_prefix_attestation_plan_v1",
                      "w1_prefix_attestation_test_plan_v1"):
        raise ValueError("unsupported external attestation plan")
    output_root = Path(plan["output_root"]).resolve()
    if target.is_relative_to(output_root) or plan_file.is_relative_to(output_root):
        raise ValueError("attestation plan and root must be outside branch outputs")
    cutoff = date.fromisoformat(plan["cutoff"])
    experiment: dict[str, Any] = {}
    if schema == "w1_prefix_attestation_plan_v1":
        if plan.get("sources") != fixed_source_sha256():
            raise ValueError("attestor source map differs from fixed reviewed SHA pins")
        from .staged_production_inputs import _build_prefix_experiment_identity
        prepared_path = Path(plan["prepared_manifest_path"])
        prepared = _read(prepared_path)
        experiment = _build_prefix_experiment_identity(
            prepared_path, prepared, PREPARED_MANIFEST_SHA256)
        if plan.get("prefix_experiment_identity") != experiment:
            raise ValueError("attestor prefix experiment identity differs from fixed inputs/runtime")
        _validate_prefix_experiment_identity(experiment)
        actual_attestor_sha = _sha(Path(__file__).resolve())
        if plan.get("attestor_sha256") != actual_attestor_sha:
            raise ValueError("attestor executable SHA differs from frozen plan")
        if (TRUSTED_PREFIX_ATTESTATOR_SHA256 is not None
                and actual_attestor_sha != TRUSTED_PREFIX_ATTESTATOR_SHA256):
            raise ValueError("attestor executable differs from independent source pin")
        sources = _check_fixed_paths(plan["sources"], "source")
        inputs = _fixed_inputs(plan)
    else:
        sources = _check_fixed_paths(plan.get("sources", {}), "test source")
        inputs = _check_fixed_paths(plan.get("inputs", {}), "test input")
    branches = plan.get("branches", {})
    required = {f"W1_{policy}_{scenario}" for policy in ("B1", "S1", "S2", "C70")
                for scenario in ("floor", "ceil")}
    if set(branches) != required:
        raise ValueError("attestation plan must bind exactly eight branches")
    if target.exists():
        raise FileExistsError(f"refusing to replace independent attestation: {target}")
    access_root = target.parent / f"{target.stem}_access"
    access_root.mkdir(parents=True, exist_ok=False)
    output_records, access_records = {}, {}
    for branch, raw_directory in branches.items():
        directory = Path(raw_directory).resolve()
        if directory.parent != output_root or not directory.is_dir():
            raise ValueError(f"branch is absent or outside output root: {branch}")
        files = _file_map(directory)
        if schema == "w1_prefix_attestation_plan_v1":
            branch_identity = _read(directory / "prefix_experiment.json")
            run_identity = _read(directory / "attempt_audit.json").get("controlled_run_identity")
            if (branch_identity != experiment or not isinstance(run_identity, dict) or any(
                    run_identity.get(key) != experiment.get(source)
                    for key, source in (("prefix_experiment_id", "experiment_id"),
                        ("prepared_core_path", "prepared_core_path"),
                        ("prepared_core_sha256", "prepared_core_sha256"),
                        ("runtime_core_path", "runtime_core_path"),
                        ("runtime_core_sha256", "runtime_core_sha256"),
                        ("experiment_config_sha256", "experiment_config_sha256")))):
                raise ValueError(f"branch dual-core identity differs from plan: {branch}")
        for name in ACCESS_FILES:
            if name not in files:
                raise ValueError(f"runner omitted access record: {branch}/{name}")
        copied_access = {}
        branch_access_root = access_root / branch
        branch_access_root.mkdir()
        for name in ACCESS_FILES:
            source = directory / name
            record = _access_record(source, cutoff)
            copy = branch_access_root / name
            copy.write_bytes(source.read_bytes())
            os.chmod(copy, stat.S_IREAD)
            copied_access[name] = {**record, "external_path": str(copy)}
        output_records[branch] = {"path": str(directory), "files": files}
        access_records[branch] = copied_access
    attestor_sha = _sha(Path(__file__).resolve())
    attestor_pinned = (TRUSTED_PREFIX_ATTESTATOR_SHA256 is not None
        and attestor_sha == TRUSTED_PREFIX_ATTESTATOR_SHA256)
    root = {"schema_version": ATTESTATION_SCHEMA,
        "status": "TEST_ONLY" if schema.endswith("test_plan_v1") else
                  "PINNED" if attestor_pinned else "UNPINNED_ATTESTATOR",
        "attestor_sha256": attestor_sha,
        "trusted_attestor_sha256": TRUSTED_PREFIX_ATTESTATOR_SHA256,
        "plan_sha256": _sha(plan_file), "cutoff": cutoff.isoformat(),
        "source_sha256": sources, "input_sha256": inputs,
        "prefix_experiment_identity": plan.get("prefix_experiment_identity"),
        "prepared_manifest_path": plan.get("prepared_manifest_path"),
        "input_config_path": plan.get("input_config_path"),
        "official_pdf_path": plan.get("official_pdf_path"),
        "branches": output_records, "read_only_access_records": access_records}
    payload = json.dumps(root, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8") + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    os.chmod(target, stat.S_IREAD)
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="外部 W1 prefix 输出哈希/访问记录见证进程")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--attestation", type=Path, required=True)
    args = parser.parse_args()
    print(attest_prefix_outputs(args.plan, args.attestation))


if __name__ == "__main__":
    main()
