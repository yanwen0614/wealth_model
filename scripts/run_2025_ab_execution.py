"""2025 A/B条件历史探索；预检桥接与--run-prepared真实core执行。"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from backtest.cnn_adapter.staged_candidate_runner import WindowDefinition
from backtest.cnn_adapter.validation_2025_bridge import (
    NpzSignal,
    Validation2025Error,
    assert_ab_equivalent,
    atomic_output_directory,
    convert_npz_to_frozen_parquet,
    derive_buy_eligibility,
    file_sha256,
    load_npz_signal,
)
from backtest.cnn_adapter.validation_2025_execution import (
    FROZEN_PROTOCOL,
    run_prepared_accounts,
)

COMMON_ANCHOR = date(2024, 12, 31)
FIRST_SIGNAL = date(2025, 1, 2)
EVALUATION_END = date(2025, 12, 16)
EXPECTED_BUFFER = (date(2025, 12, 17), date(2025, 12, 18), date(2025, 12, 19))
REQUIRED_ROLES = frozenset({"raw_market_manifest", "verified_states",
    "corporate_actions", "calendar", "benchmark", "historical_fees", "quantity_rules"})


def build_2025_window(calendar: tuple[date, ...]) -> WindowDefinition:
    """核共同anchor/E/buffer；首日信号2025-01-02必须出现在决策日。"""
    if not calendar or calendar[0] != COMMON_ANCHOR:
        raise Validation2025Error("执行日历必须以2024-12-31 anchor close开始")
    if EVALUATION_END not in calendar:
        raise Validation2025Error("完整执行日历缺2025-12-16共同E日")
    buffer = tuple(day for day in calendar if day > EVALUATION_END)
    if buffer != EXPECTED_BUFFER:
        raise Validation2025Error(f"E日后必须恰有12/17、12/18、12/19清算日，实际={buffer}")
    window = WindowDefinition(COMMON_ANCHOR, EVALUATION_END, calendar)
    if not window.signal_dates or window.signal_dates[0] != FIRST_SIGNAL:
        raise Validation2025Error("首个信号日2025-01-02丢失或日历不连续")
    return window


def validate_prepared_manifest(manifest: Mapping, *, base_dir: str | Path) -> dict:
    """验证已由调用方绑定SHA的manifest结构和覆盖门。"""
    if manifest.get("schema_version") != "validation_2025_prepared_v1":
        raise Validation2025Error("prepared manifest schema_version不符")
    if manifest.get("protocol") != FROZEN_PROTOCOL:
        raise Validation2025Error("prepared manifest未采用完全一致的冻结B1/B1预算/成本与滑点协议")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise Validation2025Error("prepared manifest必须提供artifacts列表")
    role_values = [item.get("role") for item in artifacts if isinstance(item, Mapping)]
    if any(not isinstance(role, str) for role in role_values):
        raise Validation2025Error("artifact.role必须为字符串")
    roles = set(role_values)
    if len(roles) != len(role_values):
        raise Validation2025Error("artifact.role重复，要求每个输入身份唯一")
    missing = sorted(REQUIRED_ROLES - roles)
    if missing:
        raise Validation2025Error("missing prepared inputs: " + ", ".join(missing))
    root = Path(base_dir)
    verified = []
    for item in artifacts:
        if not isinstance(item, Mapping) or not {"role", "path", "sha256"} <= set(item):
            raise Validation2025Error("artifact必须显式含role/path/sha256")
        path = Path(item["path"])
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise Validation2025Error(f"prepared artifact缺失: {item['role']} {path}")
        actual = file_sha256(path)
        if actual != str(item["sha256"]).lower():
            raise Validation2025Error(f"prepared artifact SHA-256不匹配: {item['role']} {path}")
        verified.append({"role": item["role"], "path": str(path.resolve()), "sha256": actual})
    coverage = manifest.get("coverage")
    if not isinstance(coverage, Mapping):
        raise Validation2025Error("prepared manifest缺coverage报告")
    blockers = []
    for key in ("missing_raw_count", "missing_state_count",
                "unresolved_corporate_action_count", "missing_benchmark_count"):
        value = coverage.get(key)
        if type(value) is not int or value < 0:
            blockers.append(f"{key}={value!r}")
    if coverage.get("missing_benchmark_count") != 0:
        blockers.append("benchmark coverage必须完整")
    if coverage.get("complete_calendar") is not True:
        blockers.append("complete_calendar未显式为true")
    unknown_count = coverage.get("unknown_critical_state_count")
    if type(unknown_count) is not int or unknown_count < 0:
        blockers.append(f"unknown_critical_state_count={unknown_count!r}")
    if blockers:
        raise Validation2025Error("prepared inputs INCOMPLETE: " + ", ".join(blockers))
    try:
        calendar = tuple(date.fromisoformat(value) for value in manifest["execution_calendar"])
        benchmark_dates = tuple(date.fromisoformat(value) for value in manifest["benchmark_dates"])
    except (KeyError, TypeError, ValueError) as error:
        raise Validation2025Error("manifest日历日期字段缺失或格式错误") from error
    if len(benchmark_dates) != 243 or benchmark_dates != tuple(sorted(set(benchmark_dates))):
        raise Validation2025Error("沪深300基准日历必须有243个严格递增唯一交易日")
    if benchmark_dates[0] != FIRST_SIGNAL or benchmark_dates[-1] != date(2025, 12, 31):
        raise Validation2025Error("沪深300基准日历必须覆盖2025首末交易日")
    build_2025_window(calendar)
    if not set(EXPECTED_BUFFER) <= set(benchmark_dates):
        raise Validation2025Error("benchmark日历缺E后buffer交易日")
    artifact_by_role = {item["role"]: Path(item["path"]) for item in verified}
    csv_path = artifact_by_role["calendar"]
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    try:
        source_calendar = tuple(date.fromisoformat(row["date"]) for row in rows)
    except (KeyError, TypeError, ValueError) as error:
        raise Validation2025Error("calendar CSV必须提供ISO date列") from error
    if source_calendar != benchmark_dates:
        raise Validation2025Error("calendar CSV与manifest基准日历逐日不一致")
    benchmark_closes = _validate_index(
        artifact_by_role["benchmark"], (COMMON_ANCHOR, *benchmark_dates))
    return {"artifacts": verified, "execution_calendar": calendar,
            "benchmark_dates": benchmark_dates, "coverage": dict(coverage),
            "benchmark_closes": benchmark_closes,
            "manifest_sha256": None, "protocol": FROZEN_PROTOCOL,
            "status": "INCOMPLETE" if (unknown_count or any(coverage.get(key, 0)
                for key in ("missing_raw_count", "missing_state_count",
                            "unresolved_corporate_action_count")))
                else "READY_FOR_INDEPENDENT_QA"}


def _validate_index(path: Path, calendar: tuple[date, ...]) -> dict[date, float]:
    schema = pq.ParquetFile(path).schema_arrow.names
    day_col = next((name for name in ("date", "time", "kline_time") if name in schema), None)
    if day_col is None or "close" not in schema or "code" not in schema:
        raise Validation2025Error("benchmark parquet缺code/交易日期/close列")
    columns = [day_col, "close", "code"]
    seen = {}
    expected = set(calendar)
    for batch in pq.ParquetFile(path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            raw_day = row[day_col]
            day = raw_day.date() if hasattr(raw_day, "date") else raw_day
            if day not in expected:
                continue
            if "code" in row and row["code"] != "000300.SH":
                raise Validation2025Error("benchmark混入非沪深300证券")
            close = row["close"]
            if day in seen or type(close) not in (int, float) or not math.isfinite(close) or close <= 0:
                raise Validation2025Error(f"benchmark日期重复或close无效: {day}")
            seen[day] = float(close)
    if set(seen) != expected:
        missing = sorted(expected - set(seen))
        raise Validation2025Error(f"沪深300基准缺日: {missing[:10]}")
    return seen


def load_prepared_manifest(path: str | Path, *, expected_sha256: str) -> tuple[dict, str]:
    """实际校验manifest字节SHA后才解析，禁止以JSON内自报SHA充当身份。"""
    manifest_path = Path(path)
    actual = file_sha256(manifest_path)
    if actual != expected_sha256.lower():
        raise Validation2025Error(
            f"prepared manifest SHA-256不匹配: expected={expected_sha256}, actual={actual}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise Validation2025Error("prepared manifest不是有效JSON") from error
    if not isinstance(manifest, Mapping):
        raise Validation2025Error("prepared manifest顶层必须为对象")
    return dict(manifest), actual


def _load_candidate_states(path: Path, signal: NpzSignal, calendar: tuple[date, ...],
                          *, coverage: dict | None = None):
    required = {"code", "date", "market_state", "st_known", "reference_known",
        "limit_known", "limit_up", "limit_down", "listing_known",
        "quantity_rule_known", "corporate_action_known", "st_flag",
        "absolute_limit_up_price", "absolute_limit_down_price"}
    index = {day: pos for pos, day in enumerate(calendar)}
    if any(day not in index or index[day] + 1 >= len(calendar)
           for day in signal.dates):
        raise Validation2025Error("NPZ日期缺窗口日历映射或下一执行日")
    wanted = {(code, day) for day, code in zip(signal.dates, signal.codes, strict=True)}
    states = {}
    with pq.ParquetFile(path) as parquet:
        if not required <= set(parquet.schema_arrow.names):
            raise Validation2025Error(
                f"verified_states schema缺字段: {sorted(required-set(parquet.schema_arrow.names))}")
        for batch in parquet.iter_batches(columns=sorted(required)):
            for row in batch.to_pylist():
                day = row["date"].date() if hasattr(row["date"], "date") else row["date"]
                key = row["code"], day
                if key not in wanted:
                    continue
                if key in states:
                    raise Validation2025Error(f"verified_states重复键: {key}")
                states[key] = {field: row[field] for field in required - {"code", "date"}}
    missing = wanted - set(states)
    if coverage is not None:
        coverage["missing_signal_state_count"] = len(missing)
        coverage["missing_signal_state_sample"] = sorted(
            (code, day.isoformat()) for code, day in missing)[:10]
    for code, day in missing:
        states[code, day] = {"market_state": "unknown", "st_known": False,
            "reference_known": False, "limit_known": False, "limit_up": None,
            "limit_down": None, "listing_known": False, "quantity_rule_known": False,
            "corporate_action_known": False, "st_flag": None,
            "absolute_limit_up_price": None, "absolute_limit_down_price": None}
    return states


def prepare_ab_bridges(manifest, *, base_dir: Path, verified: dict,
                       output_dir: str | Path) -> dict:
    """生成同一状态账本下的A/B冻结输入；仅写新目录，不运行账户回测。"""
    sources = manifest.get("signal_sources")
    if not isinstance(sources, Mapping) or set(sources) != {"A", "B"}:
        raise Validation2025Error("manifest.signal_sources必须恰含A和B")
    profile = {}
    for name, fields in sources.items():
        if not isinstance(fields, Mapping):
            raise Validation2025Error(f"{name} signal source必须为对象")
        required = {"npz", "npz_sha256", "checkpoint", "checkpoint_sha256",
                    "config", "config_sha256", "produced_at"}
        if not required <= set(fields):
            raise Validation2025Error(f"{name} signal source缺字段: {sorted(required-set(fields))}")
        if ("source_report" in fields) != ("source_report_sha256" in fields):
            raise Validation2025Error(f"{name} source_report路径与SHA必须同时提供")
        profile[name] = {}
        for key in ("npz", "checkpoint", "config", "source_report"):
            if key not in fields:
                continue
            path = Path(fields[key])
            profile[name][key] = path if path.is_absolute() else base_dir / path
    a = load_npz_signal(profile["A"]["npz"], expected_sha256=sources["A"]["npz_sha256"])
    b = load_npz_signal(profile["B"]["npz"], expected_sha256=sources["B"]["npz_sha256"])
    assert_ab_equivalent(a, b)
    window = build_2025_window(verified["execution_calendar"])
    expected_days = tuple(day for day in verified["benchmark_dates"]
                          if FIRST_SIGNAL <= day <= EVALUATION_END)
    if window.signal_dates != expected_days:
        raise Validation2025Error("执行窗口信号日期与完整沪深300交易日历不一致")
    if tuple(sorted(set(a.dates))) != window.signal_dates:
        raise Validation2025Error("A/B NPZ日期集合必须完整覆盖窗口每个决策日")
    state_artifact = next(item for item in verified["artifacts"]
                          if item["role"] == "verified_states")
    state_coverage = {}
    states = _load_candidate_states(Path(state_artifact["path"]), a,
                                    verified["execution_calendar"], coverage=state_coverage)
    decisions = derive_buy_eligibility(a, verified["execution_calendar"], states)
    out = Path(output_dir)
    with atomic_output_directory(out) as staged:
        result_rows = {}
        for name, signal in (("A", a), ("B", b)):
            fields = sources[name]
            hashed_state = Path(state_artifact["path"])
            bridge = convert_npz_to_frozen_parquet(
                profile[name]["npz"], expected_npz_sha256=fields["npz_sha256"],
                checkpoint_path=profile[name]["checkpoint"],
                expected_checkpoint_sha256=fields["checkpoint_sha256"],
                config_path=profile[name]["config"],
                expected_config_sha256=fields["config_sha256"],
                source_report_path=profile[name].get("source_report"),
                expected_report_sha256=fields.get("source_report_sha256"),
                produced_at=fields["produced_at"], eligibility=decisions,
                state_source_path=hashed_state,
                expected_state_source_sha256=state_artifact["sha256"],
                output_dir=staged / name)
            result_rows[name] = {"signal_path": str((out / name / "signals.parquet").resolve()),
                "npz_sha256": bridge.source_sha256, "parquet_sha256": bridge.parquet_sha256,
                "row_count": bridge.row_count,
                "ineligible_count": sum(not value.buy_eligible for value in decisions.values()),
                "checkpoint_sha256": fields["checkpoint_sha256"],
                "config_sha256": fields["config_sha256"],
                "source_report_sha256": bridge.source_report_sha256,
                "identity_status": "IDENTITY_LOCAL"}
        payload = {"schema_version": "validation_2025_ab_bridge_v1",
            "status": "INCOMPLETE" if state_coverage.get("missing_signal_state_count")
                or verified["status"] == "INCOMPLETE" else "READY_FOR_INDEPENDENT_QA",
            "execution": "BRIDGE_ONLY",
            "identity_status": "IDENTITY_LOCAL", "external_source_attestation": False,
            "pit_status": "PIT_UNPROVEN",
            "prepared_manifest_sha256": verified["manifest_sha256"],
            "window": {"anchor": COMMON_ANCHOR.isoformat(),
                       "first_signal": FIRST_SIGNAL.isoformat(),
                       "evaluation_end": EVALUATION_END.isoformat(),
                       "buffer": [day.isoformat() for day in EXPECTED_BUFFER]},
            "protocol": FROZEN_PROTOCOL,
            "coverage": {**verified["coverage"], **state_coverage},
            "sources": result_rows,
            "state_source_sha256": state_artifact["sha256"],
            "benchmark": {"anchor_close": verified["benchmark_closes"][COMMON_ANCHOR],
                "evaluation_end_close": verified["benchmark_closes"][EVALUATION_END],
                "price_index_return": verified["benchmark_closes"][EVALUATION_END]
                    / verified["benchmark_closes"][COMMON_ANCHOR] - 1,
                "dividends_reinvested": False}}
        with (staged / "bridge_manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="2025条件历史探索桥接与真实core执行")
    parser.add_argument("--prepared-manifest", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--bridge-output-dir", type=Path)
    parser.add_argument("--run-prepared", action="store_true",
                        help="运行两份独立B1真实core账户；结果始终标IDENTITY_LOCAL/PIT_UNPROVEN")
    parser.add_argument("--run-root", type=Path)
    args = parser.parse_args(argv)
    if args.prepared_manifest is None:
        parser.print_help()
        return 0
    if not args.expected_manifest_sha256:
        parser.error("--prepared-manifest必须绑定实际字节SHA-256")
    if args.run_prepared and (args.bridge_output_dir is None or args.run_root is None):
        parser.error("--run-prepared要求--bridge-output-dir和--run-root")
    if not args.run_prepared and args.run_root is not None:
        parser.error("--run-root仅能与--run-prepared同时使用")
    try:
        manifest_path = args.prepared_manifest.resolve()
        manifest, manifest_sha = load_prepared_manifest(
            manifest_path, expected_sha256=args.expected_manifest_sha256)
        verified = validate_prepared_manifest(manifest, base_dir=manifest_path.parent)
        verified["manifest_sha256"] = manifest_sha
        bridges = (prepare_ab_bridges(manifest, base_dir=manifest_path.parent,
                    verified=verified, output_dir=args.bridge_output_dir)
                   if args.bridge_output_dir else None)
        execution = None
        if args.run_prepared:
            assert bridges is not None and args.run_root is not None
            execution = run_prepared_accounts(manifest=manifest, base_dir=manifest_path.parent,
                verified=verified, bridge_payload=bridges, run_root=args.run_root)
    except Exception as error:  # noqa: BLE001 - 所有输入/执行失败均 fail-closed 为INCOMPLETE
        print(f"INCOMPLETE: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": execution["status"] if execution else verified["status"],
                      "execution": execution or "BRIDGE_ONLY", "window": {
                          "anchor": COMMON_ANCHOR.isoformat(),
                          "first_signal": FIRST_SIGNAL.isoformat(),
                          "evaluation_end": EVALUATION_END.isoformat(),
                          "buffer": [day.isoformat() for day in EXPECTED_BUFFER]},
                      "verified_artifacts": verified["artifacts"],
                      "bridge_manifest": bridges}, indent=2))
    final_status = execution["status"] if execution else verified["status"]
    return 0 if final_status in {"COMPLETED", "READY_FOR_INDEPENDENT_QA"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
