"""真实core上的条件历史探索A/B执行与本地来源审计。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts.config import CostConfig
from backtest_core.contracts.protocols import MarketDataProvider

from backtest.cnn_adapter.corporate_action_snapshot_loader import (
    CorporateActionSnapshot,
    load_corporate_action_snapshot,
)
from backtest.cnn_adapter.historical_costs import resolve_historical_costs
from backtest.cnn_adapter.quantity_rules import QuantityRule
from backtest.cnn_adapter.raw_market_inputs import (
    normalize_raw_market_frame,
    read_raw_market_inputs,
)
from backtest.cnn_adapter.raw_market_provider import CnnRawMarketDataProvider
from backtest.cnn_adapter.staged_allocation import Policy, budget_per_episode
from backtest.cnn_adapter.staged_candidate_runner import (
    StagedWindowConfig,
    StagedWindowOutcome,
    WindowDefinition,
    run_staged_window,
)
from backtest.cnn_adapter.staged_production_inputs import _quantity_resolver
from backtest.cnn_adapter.validation_2025_bridge import _validate_config, load_npz_signal


def _verify_bridge_rows(path: Path, signal, *, npz_sha: str, checkpoint_sha: str,
                        config_sha: str, state_sha: str, decisions) -> str:
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    table = pq.read_table(path)
    required = {"date", "code", "exp_ret", "true_ret", "buy_eligible",
                "source_npz_sha256", "checkpoint_sha256", "config_sha256",
                "state_source_sha256", "model_horizon", "identity_status",
                "status", "execution_status", "buy_rejection_reasons"}
    if not required <= set(table.column_names) or table.num_rows != len(signal.dates):
        raise ValueError("bridge parquet字段或NPZ行数不匹配")
    rows = table.to_pylist()
    for index, row in enumerate(rows):
        key = (signal.dates[index], signal.codes[index])
        if ((row["date"], row["code"]) != key
                or row["exp_ret"] != signal.exp_ret[index]
                or row["true_ret"] != signal.true_ret[index]
                or row["buy_eligible"] is not decisions[key].buy_eligible
                or row["status"] != "ready"
                or row["execution_status"] != decisions[key].execution_status
                or row["buy_rejection_reasons"] != list(decisions[key].reasons)
                or row["source_npz_sha256"] != npz_sha
                or row["checkpoint_sha256"] != checkpoint_sha
                or row["config_sha256"] != config_sha
                or row["state_source_sha256"] != state_sha
                or row["model_horizon"] != 10
                or row["identity_status"] != "IDENTITY_LOCAL"):
            raise ValueError(f"bridge parquet与原始NPZ/状态派生不一致: row={index} {key}")
    return actual_sha

FROZEN_PROTOCOL = {
    "initial_capital": 1_000_000,
    "policy": "B1",
    "budget_per_episode": 200_000,
    "max_slots": 5,
    "buy_rank_max": 5,
    "exit_rank_min": 11,
    "max_positions": 10,
    "model_horizon": 10,
    "commission_rate": 0.0002,
    "minimum_commission": 5,
    "stamp_tax_rate_2025_sell": 0.0005,
    "transfer_fee_rate_both_sides": 0.00001,
    "slippage": {"kind": "sigma_adv", "impact_coefficient": 1,
        "adv_window": 20, "sigma_window": 20, "sigma_clip": [0.005, 0.08],
        "participation_cap": 0.10, "spread_floor": 0.0002,
        "slip_max": 0.05, "missing_volume_policy": "warn"},
    "tax_scenario": "cash_dividend_20pct_stress_assumption_only",
}


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unknown_coverage_count(path: Path) -> int:
    if not path.is_file():
        return -1
    unknown = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            unknown += bool(row.get("unknown_fields")) or row.get("bar_present") is not True
    return unknown


def _cost_config() -> CostConfig:
    return CostConfig(commission_rate=0.0002, commission_rate_buy=0.0002,
        commission_rate_sell=0.0002, min_commission=5, stamp_tax_rate=0.0005,
        transfer_fee_rate=0.00001, impact_coefficient=1, adv_window=20,
        sigma_window=20, sigma_clip=(0.005, 0.08), p_cap=0.10,
        spread_floor=0.0002, slip_max=0.05, missing_volume_policy="warn")


class _LocalStateLookup:
    """按代码懒读本地状态；从不将来源或known_at提升为PIT证明。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._code: str | None = None
        self._rows: dict[date, dict[str, Any]] = {}

    def get(self, key: tuple[str, date], default=None):
        code, day = key
        if self._code != code:
            table = pq.read_table(self.path, filters=[("code", "==", code)])
            rows: dict[date, dict[str, Any]] = {}
            for row in table.to_pylist():
                row_day = row.pop("date")
                if row_day in rows:
                    raise ValueError(f"verified_states重复键: {code} {row_day}")
                rows[row_day] = row
            self._code, self._rows = code, rows
        state = self._rows.get(day)
        if state is None:
            return default
        return {**state,
            "market_state_known": state.get("market_state") in ("trading", "suspended")
                and state.get("listing_known") is True,
            "st_state_known": state.get("st_known") is True
                and type(state.get("st_flag")) is bool,
            "limit_state_known": state.get("limit_known") is True
                and state.get("quantity_rule_known") is True
                and state.get("corporate_action_known") is True
                and type(state.get("limit_up")) is bool
                and type(state.get("limit_down")) is bool
                and all(not isinstance(state.get(field), bool)
                    and isinstance(state.get(field), (int, float))
                    and isfinite(state[field]) and state[field] > 0
                    for field in ("absolute_limit_up_price", "absolute_limit_down_price"))}


class _ScopedRawProvider(CnnRawMarketDataProvider):
    """将经逐文件SHA核验的本地Parquet/HDF原始记录接入现有core provider。"""

    def __init__(self, files, states, *, window, action_dates):
        super().__init__(Path("."), signal_start=window.signal_dates[0],
            signal_end=window.evaluation_end, execution_end=window.execution_calendar[-1],
            verified_states=states, corporate_action_dates=action_dates,
            history_bars=21, allow_empty_window=frozenset())
        self.files = files
        self.window = window

    def _load(self, instrument_id: str) -> None:
        if instrument_id in self._records:
            return
        source = self.files.get(instrument_id)
        if source is None:
            self._records[instrument_id] = {}
            return
        path, metadata = source
        if path.suffix.casefold() in {".h5", ".hdf", ".hdf5"}:
            frame = cast(pd.DataFrame, pd.read_hdf(path, key=metadata.get("key")))
            columns = metadata.get("columns", {})
            if columns:
                frame = frame.rename(columns={source_name: canonical
                    for canonical, source_name in columns.items()})
            if "code" not in frame.columns:
                frame["code"] = instrument_id
            frame = frame.loc[frame["code"].astype(str) == instrument_id]
            window = normalize_raw_market_frame(frame, instrument_id=instrument_id,
                signal_start=self.window.signal_dates[0], signal_end=self.window.evaluation_end,
                execution_end=self.window.execution_calendar[-1], history_bars=21,
                allow_empty_window=True)
        elif path.suffix.casefold() == ".parquet":
            window = read_raw_market_inputs(path, instrument_id=instrument_id,
                signal_start=self.window.signal_dates[0], signal_end=self.window.evaluation_end,
                execution_end=self.window.execution_calendar[-1], history_bars=21,
                allow_empty_window=True)
        else:
            raise ValueError(f"本地原始行情只接受parquet或明确列映射的HDF: {path}")
        self._records[instrument_id] = {row.trading_date: row for row in window.records}


def _load_local_raw_manifest(path: str | Path, *, base_dir: Path, expected_codes):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "validation_2025_local_raw_v1":
        raise ValueError("raw_market_manifest schema_version缺失或不符")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise TypeError("raw_market_manifest.files必须为数组")
    files = {}
    for item in entries:
        if not isinstance(item, Mapping) or not {"code", "path", "sha256"} <= set(item):
            raise ValueError("每个本地raw文件必须提供code/path/sha256")
        code = item["code"]
        source = Path(item["path"])
        if not source.is_absolute():
            source = base_dir / source
        if code not in expected_codes or code in files or not source.is_file():
            raise ValueError(f"本地raw代码、重复键或文件路径无效: {code} {source}")
        actual = _sha256(source)
        if actual != str(item["sha256"]).lower():
            raise ValueError(f"本地raw实际文件SHA不匹配: {source}")
        files[code] = (source, dict(item))
    missing_codes = sorted(set(expected_codes) - set(files))
    return files, {
        "source_kind_declared": manifest.get("source_kind", "local_unknown"),
        "universe_scope": manifest.get("universe_scope", "partial_local"),
        "expected_code_count": len(set(expected_codes)),
        "available_code_count": len(files),
        "missing_code_count": len(missing_codes),
        "missing_codes_sample": missing_codes[:20],
        "scope_status": "PARTIAL_LOCAL_HDF" if missing_codes
            and "hdf" in str(manifest.get("source_kind", "")).casefold()
            else ("PARTIAL_LOCAL" if missing_codes else "LOCAL_SCOPE_UNVERIFIED"),
        "source_identity_status": "IDENTITY_LOCAL",
        "source_origin_status": "UNKNOWN",
        "source_sha256": _sha256(path),
    }


def run_ab_core(*, window: WindowDefinition, signal_paths: Mapping[str, Path],
                signal_sha256: Mapping[str, str], checkpoint_sha256: Mapping[str, str],
                market_factory: Callable[[str], MarketDataProvider],
                corporate_action_snapshot: CorporateActionSnapshot,
                quantity_rule_resolver: Callable[[date, str], QuantityRule],
                benchmark_closes: Mapping[date, float], run_root: str | Path,
                scope: Mapping[str, Any]) -> dict[str, Any]:
    """A/B各自新建core账户；一侧失败仅隔离该账户并保留其core审计。"""
    if set(signal_paths) != {"A", "B"} or set(signal_sha256) != {"A", "B"}:
        raise ValueError("run-prepared必须同时提供A/B两份冻结信号")
    if set(checkpoint_sha256) != {"A", "B"}:
        raise ValueError("run-prepared必须同时提供A/B checkpoint身份")
    if (window.anchor_date != date(2024, 12, 31)
            or window.evaluation_end != date(2025, 12, 16)
            or tuple(window.buffer_dates) != tuple(date(2025, 12, d) for d in (17, 18, 19))
            or not window.signal_dates or window.signal_dates[0] != date(2025, 1, 2)):
        raise ValueError("执行窗口必须匹配2025冻结anchor/首信号/E/buffer")
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=False)
    results: dict[str, Any] = {}
    base_cost = _cost_config()
    for source in ("A", "B"):
        output = root / source
        status: dict[str, Any] = {"source": source, "output_dir": str(output),
            "policy": Policy.B1.value, "tranche_budget": budget_per_episode(1_000_000),
            "identity_status": "IDENTITY_LOCAL", "pit_status": "PIT_UNPROVEN"}
        try:
            actual_signal_sha = _sha256(signal_paths[source])
            if actual_signal_sha != signal_sha256[source]:
                raise ValueError(f"{source}冻结signal parquet SHA不匹配")
            if len(checkpoint_sha256[source]) != 64:
                raise ValueError(f"{source}缺checkpoint SHA身份")
            config = StagedWindowConfig(source_id=f"2025_{source}",
                signal_file_sha256=signal_sha256[source],
                checkpoint_sha256=checkpoint_sha256[source], initial_capital=1_000_000,
                policy=Policy.B1, tick_size=0.01, lot_size=100,
                tax_policy="cash_dividend_20pct_stress", cost_config=base_cost,
                period_id=f"2025_{source}", require_known_share_tax=False)
            def cost_resolver(day: date, code: str) -> CostConfig:
                return resolve_historical_costs(execution_date=day,
                    market="SSE_A" if code.endswith(".SH") else "SZSE_A",
                    commission=base_cost)
            outcome: StagedWindowOutcome = run_staged_window(window=window, config=config,
                signal_parquet_path=signal_paths[source], market=market_factory(source),
                corporate_action_snapshot=corporate_action_snapshot,
                cost_config_resolver=cost_resolver,
                quantity_rule_resolver=quantity_rule_resolver, output_dir=output)
            coverage_unknown = _unknown_coverage_count(output / "market_coverage.jsonl")
            status.update(status="COMPLETED", mechanical_status=outcome.mechanical_status,
                production_acceptance=outcome.production_acceptance,
                validation_failures=list(outcome.validation_failures),
                main_return=float(outcome.provenance["main_total_return"]),
                unknown_market_code_days=coverage_unknown,
                core_manifest_sha256=outcome.manifest_sha256)
        except Exception as error:  # noqa: BLE001 - 每个账户独立记录失败，继续执行另一账户
            status.update(status="INCOMPLETE", error_type=type(error).__name__, error=str(error))
            output.mkdir(exist_ok=True)
            (output / "run_prepared_error.json").write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        results[source] = status
    required_benchmark = (window.anchor_date, window.evaluation_end, window.buffer_dates[-1])
    if any(day not in benchmark_closes for day in required_benchmark):
        raise ValueError("benchmark缺anchor/E/buffer末日close")
    anchor_close = benchmark_closes[window.anchor_date]
    end_close = benchmark_closes[window.evaluation_end]
    if anchor_close <= 0 or end_close <= 0:
        raise ValueError("benchmark close必须为正数")
    payload = {
        "schema_version": "validation_2025_core_execution_v1",
        "execution": "COMPLETED_CONDITIONAL_HISTORICAL_EXPLORATION",
        "status": "INCOMPLETE" if (not all(r["status"] == "COMPLETED"
            for r in results.values()) or scope.get("missing_code_count", 0)
            or scope.get("unknown_critical_state_count", 0)
            or scope.get("missing_state_count", 0)
            or scope.get("unresolved_corporate_action_count", 0)
            or any(r.get("unknown_market_code_days", -1) != 0 for r in results.values())
            or scope.get("pit_status") == "PIT_UNPROVEN") else "COMPLETED",
        "identity_status": "IDENTITY_LOCAL",
        "external_source_attestation": False,
        "pit_status": "PIT_UNPROVEN",
        "production_qualification": "NOT_QUALIFIED",
        "scope": dict(scope),
        "window": {"anchor": window.anchor_date.isoformat(),
                   "first_signal": window.signal_dates[0].isoformat(),
                   "evaluation_end": window.evaluation_end.isoformat(),
                   "buffer": [day.isoformat() for day in window.buffer_dates]},
        "benchmark": {"anchor_close": anchor_close, "evaluation_end_close": end_close,
            "return": end_close / anchor_close - 1,
            "buffer_end_close": benchmark_closes[window.buffer_dates[-1]],
            "dividends_reinvested": False},
        "protocol": FROZEN_PROTOCOL,
        "accounts": results,
    }
    (root / "execution_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (root / "execution_manifest.sha256").write_text(
        _sha256(root / "execution_manifest.json"), encoding="ascii")
    return payload


def run_prepared_accounts(*, manifest: Mapping[str, Any], base_dir: Path,
                          verified: Mapping[str, Any], bridge_payload: Mapping[str, Any],
                          run_root: str | Path) -> dict[str, Any]:
    """校验真实本地源后组装raw/state/CA/fee/quantity输入并启动A/B core。"""
    run_inputs = manifest.get("run_inputs")
    required = {"corporate_action_root", "raw_market_scope"}
    if not isinstance(run_inputs, Mapping) or not required <= set(run_inputs):
        raise ValueError("INCOMPLETE: run_inputs缺corporate_action_root/raw_market_scope")
    artifacts = {item["role"]: item for item in verified["artifacts"]}
    for item in verified["artifacts"]:
        if _sha256(item["path"]) != item["sha256"]:
            raise ValueError(f"prepared artifact实际SHA已变化: {item['role']}")
    if (bridge_payload.get("schema_version") != "validation_2025_ab_bridge_v1"
            or bridge_payload.get("protocol") != FROZEN_PROTOCOL
            or set(bridge_payload.get("sources", {})) != {"A", "B"}):
        raise ValueError("INCOMPLETE: A/B桥接清单版本、协议或来源缺失")
    roles = {"raw_market_manifest", "verified_states", "corporate_actions", "quantity_rules"}
    if not roles <= set(artifacts):
        raise ValueError(f"INCOMPLETE: run-prepared缺少artifact roles: {sorted(roles-set(artifacts))}")
    sources = manifest["signal_sources"]
    signal_profiles = {}
    checkpoint_hashes, config_hashes = {}, {}
    for name in ("A", "B"):
        fields = sources[name]
        signal = load_npz_signal(_resolve(base_dir, fields["npz"]),
                                 expected_sha256=fields["npz_sha256"])
        checkpoint_path = _resolve(base_dir, fields["checkpoint"])
        config_path = _resolve(base_dir, fields["config"])
        checkpoint_actual = _sha256(checkpoint_path)
        if checkpoint_actual != str(fields["checkpoint_sha256"]).lower():
            raise ValueError(f"{name} checkpoint实际SHA不匹配")
        _, config_actual = _validate_config(config_path, fields["config_sha256"])
        checkpoint_hashes[name], config_hashes[name] = checkpoint_actual, config_actual
        signal_profiles[name] = signal
    if (signal_profiles["A"].dates != signal_profiles["B"].dates
            or signal_profiles["A"].codes != signal_profiles["B"].codes
            or signal_profiles["A"].true_ret != signal_profiles["B"].true_ret):
        raise ValueError("A/B原始NPZ身份未逐行一致")
    from backtest.cnn_adapter.validation_2025_bridge import derive_buy_eligibility
    from scripts.run_2025_ab_execution import _load_candidate_states

    states_path = Path(artifacts["verified_states"]["path"])
    state_coverage: dict[str, Any] = {}
    candidate_states = _load_candidate_states(states_path, signal_profiles["A"],
        tuple(verified["execution_calendar"]), coverage=state_coverage)
    decisions = derive_buy_eligibility(signal_profiles["A"],
        tuple(verified["execution_calendar"]), candidate_states)
    codes = set(signal_profiles["A"].codes)
    raw_files, raw_scope = _load_local_raw_manifest(
        artifacts["raw_market_manifest"]["path"], base_dir=base_dir, expected_codes=codes)
    if run_inputs["raw_market_scope"] != raw_scope["universe_scope"]:
        raise ValueError("run_inputs.raw_market_scope与raw manifest声明冲突")
    state_lookup = _LocalStateLookup(states_path)
    unknown_state_count = 0
    missing_state_count = 0
    for code in codes:
        for day in verified["execution_calendar"]:
            state = state_lookup.get((code, day))
            if state is None:
                missing_state_count += 1
                unknown_state_count += 1
            elif (state.get("market_state") not in ("trading", "suspended")
                  or state.get("st_known") is not True
                  or state.get("reference_known") is not True
                  or state.get("limit_known") is not True
                  or state.get("listing_known") is not True
                  or state.get("quantity_rule_known") is not True
                  or state.get("corporate_action_known") is not True
                  or type(state.get("st_flag")) is not bool
                  or type(state.get("limit_up")) is not bool
                  or type(state.get("limit_down")) is not bool
                  or any(type(state.get(field)) not in (int, float)
                         or not isfinite(state[field]) or state[field] <= 0
                         for field in ("absolute_limit_up_price", "absolute_limit_down_price"))):
                unknown_state_count += 1
    ca_item = artifacts["corporate_actions"]
    ca_root = _resolve(base_dir, run_inputs["corporate_action_root"])
    snapshot = load_corporate_action_snapshot(ca_root,
        manifest_path=ca_item["path"], expected_manifest_sha256=ca_item["sha256"])
    quantity_config = json.loads(Path(artifacts["quantity_rules"]["path"]).read_text(
        encoding="utf-8"))
    quantity_artifacts: dict[str, str] = {}
    quantity = _quantity_resolver(quantity_config, quantity_artifacts)
    window = WindowDefinition(date(2024, 12, 31), date(2025, 12, 16),
                              tuple(verified["execution_calendar"]))
    action_dates = frozenset((item.instrument_id, item.event.ex_date)
        for item in snapshot.descriptors if item.event is not None)
    def market_factory(_source: str) -> MarketDataProvider:
        return _ScopedRawProvider(raw_files, _LocalStateLookup(states_path),
                                  window=window, action_dates=action_dates)
    scope = {**raw_scope, "expected_signal_rows": len(signal_profiles["A"].codes),
        "unknown_critical_state_count": unknown_state_count,
        "missing_state_count": missing_state_count,
        "unresolved_corporate_action_count": sum(bool(item.unknown)
                                                  for item in snapshot.descriptors),
        "quantity_artifact_count": len(quantity_artifacts),
        "state_source_sha256": artifacts["verified_states"]["sha256"],
        "corporate_action_manifest_sha256": snapshot.manifest_sha256,
        "prepared_manifest_sha256": verified.get("manifest_sha256"),
        "pit_status": "PIT_UNPROVEN"}
    signal_paths, signal_hashes = {}, {}
    for name in ("A", "B"):
        bridge = bridge_payload["sources"][name]
        if bridge.get("npz_sha256") != signal_profiles[name].source_sha256:
            raise ValueError(f"{name}桥接来源NPZ SHA与原始NPZ不一致")
        if str(bridge.get("checkpoint_sha256", "")).lower() != checkpoint_hashes[name]:
            raise ValueError(f"{name}桥接checkpoint SHA与原始模型不一致")
        signal_path = Path(bridge["signal_path"])
        signal_paths[name] = signal_path
        signal_hashes[name] = _verify_bridge_rows(signal_path, signal_profiles[name],
            npz_sha=signal_profiles[name].source_sha256,
            checkpoint_sha=checkpoint_hashes[name],
            config_sha=config_hashes[name],
            state_sha=artifacts["verified_states"]["sha256"], decisions=decisions)
    checkpoints = checkpoint_hashes
    return run_ab_core(window=window, signal_paths=signal_paths,
        signal_sha256=signal_hashes, checkpoint_sha256=checkpoints,
        market_factory=market_factory, corporate_action_snapshot=snapshot,
        quantity_rule_resolver=quantity, benchmark_closes=verified["benchmark_closes"],
        run_root=run_root, scope=scope)


def _resolve(base_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path
