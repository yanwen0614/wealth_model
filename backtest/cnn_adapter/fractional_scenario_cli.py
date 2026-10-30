"""生成或执行固定 W1×策略×整数化分支；不含 W2。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .fractional_prefix_gate import validate_prefix_proof
from .fractional_scenarios import OFFICIAL_PDF_SHA256
from .staged_production_inputs import file_sha256

V12_MANIFEST_SHA256 = "a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441"
POLICIES = ("B1", "S1", "S2", "C70")
SCENARIOS = ("floor", "ceil")
PREFIX_CUTOFF = "2021-06-07"


def build_commands(prepared_path: Path, input_config: Path, pdf_path: Path,
                   output_root: Path, prefix_proof_path: Path | None = None,
                   expected_prefix_proof_sha256: str | None = None, *,
                   prefix_only: bool = False,
                   conditional_only: bool = False) -> list[dict[str, object]]:
    """核验冻结 manifest 和 PDF 后构造全部八条独立命令。"""
    if prefix_only and conditional_only:
        raise ValueError("prefix-only and conditional-only are mutually exclusive")
    file_sha256(prepared_path, V12_MANIFEST_SHA256)
    file_sha256(pdf_path, OFFICIAL_PDF_SHA256)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    config = prepared["config"]
    if json.loads(input_config.read_text(encoding="utf-8")) != config:
        raise ValueError("输入配置与v12 prepared manifest不同")
    if prepared["schema_version"] != "staged_prepared_v1" or "W1" not in config["windows"]:
        raise ValueError("prepared inputs 不是固定 v12 W1 输入")
    spec = config["windows"]["W1"]
    calendar = Path(prepared["output_dir"]) / "calendar_W1.txt"
    commands = []
    for policy in POLICIES:
        for scenario in SCENARIOS:
            branch = f"W1_{policy}_{scenario}"
            output = output_root / branch
            args = [sys.executable, "-B", "-m", "backtest.cnn_adapter.staged_candidate_runner",
                    "--signal-parquet", spec["signal_path"], "--expected-sha256", spec["signal_sha256"],
                    "--source-id", spec["source_id"], "--checkpoint-sha256", spec["checkpoint_sha256"],
                    "--anchor-date", spec["anchor"], "--evaluation-end", spec["evaluation_end"],
                    "--execution-calendar", str(calendar), "--policy", policy, "--output-dir", str(output)]
            args += ["--initial-capital", str(config["initial_capital"]), "--tax-policy", config["tax_policy"]]
            args += ["--input-config", str(input_config), "--prepared-manifest", str(prepared_path),
                     "--research-mode", "exploration", "--fractional-scenario", scenario,
                       "--official-pdf", str(pdf_path)]
            if conditional_only:
                args += ["--conditional-simulation"]
            if prefix_only:
                args += ["--prefix-stop-after-close", PREFIX_CUTOFF,
                         "--information-cutoff", PREFIX_CUTOFF,
                         "--prefix-experiment"]
            if prefix_proof_path is not None and expected_prefix_proof_sha256 is not None:
                args += ["--prefix-proof", str(prefix_proof_path),
                         "--expected-prefix-proof-sha256", expected_prefix_proof_sha256]
            commands.append({"branch": branch, "policy": policy, "scenario": scenario,
                             "output_dir": str(output), "argv": args})
    if len(commands) != 8:
        raise AssertionError("all four policies and both scenarios must be present")
    return commands


def write_attestation_plan(prepared_path: Path, input_config: Path, pdf_path: Path,
                           output_root: Path, plan_path: Path) -> str:
    """按冻结 manifest 生成 runner 外部的输入/源码/八目录哈希计划。"""
    prepared_sha = file_sha256(prepared_path, V12_MANIFEST_SHA256)
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    config = json.loads(input_config.read_text(encoding="utf-8"))
    if config != prepared.get("config"):
        raise ValueError("attestation plan config differs from frozen manifest")
    from .staged_production_inputs import _build_prefix_experiment_identity
    experiment_identity = _build_prefix_experiment_identity(prepared_path, prepared, prepared_sha)
    file_sha256(pdf_path, OFFICIAL_PDF_SHA256)
    from .prefix_attestor import fixed_source_sha256
    sources = fixed_source_sha256()
    for raw_path, expected in sources.items():
        file_sha256(raw_path, expected)
    attestor_path = Path(__file__).with_name("prefix_attestor.py")
    attestor_sha256 = file_sha256(attestor_path)
    inputs = {str(Path(path).resolve()): digest
              for path, digest in prepared.get("artifacts", {}).items()}
    inputs.update({str(prepared_path.resolve()): prepared_sha,
        str(prepared_path.with_suffix(".sha256").resolve()): file_sha256(
            prepared_path.with_suffix(".sha256")),
        str(input_config.resolve()): file_sha256(input_config),
        str(pdf_path.resolve()): OFFICIAL_PDF_SHA256})
    branches = {f"W1_{policy}_{scenario}":
        str((output_root / f"W1_{policy}_{scenario}").resolve())
        for policy in POLICIES for scenario in SCENARIOS}
    target, output = plan_path.resolve(), output_root.resolve()
    if target.is_relative_to(output):
        raise ValueError("attestation plan must be outside runner output root")
    plan = {"schema_version": "w1_prefix_attestation_plan_v1",
        "output_root": str(output), "cutoff": PREFIX_CUTOFF,
        "sources": sources, "inputs": inputs, "branches": branches,
        "prefix_experiment_identity": experiment_identity,
        "attestor_sha256": attestor_sha256,
        "prepared_manifest_path": str(prepared_path.resolve()),
        "input_config_path": str(input_config.resolve()),
        "official_pdf_path": str(pdf_path.resolve())}
    payload = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8") + b"\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(payload)
    return hashlib.sha256(payload).hexdigest()


def execute(commands: list[dict[str, object]], output_root: Path,
            prefix_proof_path: Path | None = None,
            expected_prefix_proof_sha256: str | None = None, *,
            prefix_only: bool = False,
            conditional_only: bool = False) -> list[dict[str, object]]:
    """逐支执行且保留失败；输出根必须新建，禁止覆盖旧证据。"""
    if prefix_only and conditional_only:
        raise ValueError("prefix-only and conditional-only are mutually exclusive")
    if prefix_only:
        if prefix_proof_path is not None or expected_prefix_proof_sha256 is not None:
            raise ValueError("prefix-only runner cannot consume a future proof")
        for item in commands:
            argv = item.get("argv")
            if (not isinstance(argv, list) or "--prefix-stop-after-close" not in argv
                    or "--information-cutoff" not in argv):
                raise ValueError("prefix-only command set lacks explicit cutoff arguments")
            for flag in ("--prefix-stop-after-close", "--information-cutoff"):
                index = argv.index(flag)
                if index + 1 >= len(argv) or argv[index + 1] != PREFIX_CUTOFF:
                    raise ValueError(f"prefix-only command must use fixed {PREFIX_CUTOFF} cutoff")
    elif not conditional_only:
        validate_prefix_proof(prefix_proof_path, expected_prefix_proof_sha256)
    if conditional_only:
        if prefix_proof_path is not None or expected_prefix_proof_sha256 is not None:
            raise ValueError("conditional-only cannot consume a prefix proof")
        for item in commands:
            argv = item.get("argv")
            if (not isinstance(argv, list) or "--conditional-simulation" not in argv
                    or "--prefix-stop-after-close" in argv or "--prefix-proof" in argv):
                raise ValueError("conditional command set must be full-window and explicitly isolated")
    output_root.mkdir(parents=True, exist_ok=False)
    results = []
    for item in commands:
        branch = str(item["branch"])
        argv = item["argv"]
        if not isinstance(argv, list) or not all(isinstance(part, str) for part in argv):
            raise TypeError("command argv must be a string list")
        completed = subprocess.run(argv, cwd=Path.cwd(), capture_output=True, text=True)
        (output_root / f"{branch}.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (output_root / f"{branch}.stderr.log").write_text(completed.stderr, encoding="utf-8")
        attempt = Path(str(item["output_dir"])) / "attempt_audit.json"
        audit = json.loads(attempt.read_text(encoding="utf-8")) if attempt.is_file() else {}
        mechanical = audit.get("mechanical_status")
        status = ("FAILED" if completed.returncode else
                  "COMPLETE" if mechanical == "PASS" else "INCOMPLETE")
        results.append({"branch": branch, "exit_code": completed.returncode,
                        "status": status, "mechanical_status": mechanical,
                        "certification": "NOT_CERTIFIED_CONDITIONAL" if conditional_only
                        else "proof_gated",
                        "output_dir": item["output_dir"]})
        branch_dir = Path(str(item["output_dir"]))
        if status != "COMPLETE" and not branch_dir.exists():
            branch_dir.mkdir(parents=True, exist_ok=False)
            (branch_dir / "branch_failure.json").write_text(
                json.dumps(results[-1] | {"argv": argv}, ensure_ascii=False, indent=2),
                encoding="utf-8")
    (output_root / "branch_status.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="W1 300502 floor/ceil 八分支条件情景")
    parser.add_argument("--prepared-manifest", required=True, type=Path)
    parser.add_argument("--input-config", required=True, type=Path)
    parser.add_argument("--official-pdf", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="执行性能候选分支，需可信 proof")
    mode.add_argument("--run-prefixes", action="store_true",
                      help="执行 cutoff 前缀分支，不计算绩效且不需要先有 proof")
    mode.add_argument("--run-conditional-simulations", action="store_true",
                      help="执行八支完整 W1 条件模拟；结果未认证且不进入生产门")
    parser.add_argument("--prefix-proof", type=Path)
    parser.add_argument("--expected-prefix-proof-sha256")
    parser.add_argument("--attestation-plan", type=Path)
    parser.add_argument("--attestation-root", type=Path)
    args = parser.parse_args()
    if not (Path.cwd() / "backtest/cnn_adapter/staged_candidate_runner.py").is_file():
        raise RuntimeError("请以隔离目标 worktree 作为当前目录")
    if args.execute:
        validate_prefix_proof(args.prefix_proof, args.expected_prefix_proof_sha256)
    if args.run_prefixes and (args.attestation_plan is None or args.attestation_root is None):
        parser.error("--run-prefixes requires external --attestation-plan and --attestation-root")
    if args.run_conditional_simulations and (args.attestation_plan is not None
            or args.attestation_root is not None or args.prefix_proof is not None
            or args.expected_prefix_proof_sha256 is not None):
        parser.error("conditional simulations do not accept proof or attestation inputs")
    if args.run_prefixes:
        from .prefix_ledger_verifier import PREFIX_ATTESTATION_ROOT
        if args.attestation_root.resolve() != PREFIX_ATTESTATION_ROOT.resolve():
            parser.error("--attestation-root must use the fixed external trust-root path")
        write_attestation_plan(args.prepared_manifest, args.input_config,
            args.official_pdf, args.output_root, args.attestation_plan)
    commands = build_commands(args.prepared_manifest, args.input_config,
                              args.official_pdf, args.output_root,
                              args.prefix_proof if args.execute else None,
                               args.expected_prefix_proof_sha256 if args.execute else None,
                               prefix_only=args.run_prefixes,
                               conditional_only=args.run_conditional_simulations)
    if args.execute or args.run_prefixes or args.run_conditional_simulations:
        results = execute(commands, args.output_root, args.prefix_proof,
                          args.expected_prefix_proof_sha256,
                          prefix_only=args.run_prefixes,
                          conditional_only=args.run_conditional_simulations)
        if args.run_prefixes and all(item["status"] == "COMPLETE" for item in results):
            attestor = [sys.executable, "-B", "-m", "backtest.cnn_adapter.prefix_attestor",
                        "--plan", str(args.attestation_plan),
                        "--attestation", str(args.attestation_root)]
            completed = subprocess.run(attestor, cwd=Path.cwd(), check=True,
                                       capture_output=True, text=True)
            print(f"external_attestation_sha256={completed.stdout.strip()}")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(commands, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
