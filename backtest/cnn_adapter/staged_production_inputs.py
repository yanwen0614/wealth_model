"""冻结输入准备与八窗调度；账户、策略和公司行动均复用现有契约。"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import inspect
import json
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from math import isfinite
from pathlib import Path
from time import perf_counter
from types import MappingProxyType
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.contracts.config import CostConfig
from backtest_core.engine import run_account_backtest_from_orders

from .corporate_action_snapshot_loader import load_corporate_action_snapshot
from .historical_costs import resolve_historical_costs
from .quantity_rules import MappingQuantityRuleResolver, QuantityRule
from .raw_market_inputs import read_raw_market_inputs
from .raw_market_provider import CnnRawMarketDataProvider
from .staged_allocation import Policy
from .staged_candidate_runner import (
    StagedWindowConfig,
    WindowDefinition,
    _market_coverage,
    _signal_content_fingerprint,
    build_signal_ranking,
    load_frozen_signal_parquet,
    run_staged_window,
)

_FIELDS = ("market_code", "trade_date_str", "preclose", "high_limited", "low_limited",
           "high_lmt_rate", "low_lmt_rate", "is_st_sec", "is_susp_sec", "is_wd_sec", "is_xr_sec")
_FLOATS = frozenset(_FIELDS[2:7])


def file_sha256(path: str | Path, expected: str | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if expected is not None and actual != expected:
        raise ValueError(f"输入 SHA256 不匹配: {path}")
    return actual


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str),
                          encoding="utf-8")


def _positive(value):
    return type(value) in (int, float) and isfinite(value) and value > 0


def canonical_row_hash(row):
    payload = {key: float(row[key]) if key in _FLOATS and row[key] is not None
               else row[key] for key in _FIELDS}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")).encode()).hexdigest()


def derive_execution_state(row, raw):
    """只用显式 SDK 值及执行开盘；前收是当日调整参考，WD/XR仅留原值。"""
    upper, lower = row["high_limited"], row["low_limited"]
    bounds = _positive(upper) and _positive(lower) and lower <= upper
    opening = None if raw is None else raw.open
    known = bounds and _positive(opening)
    def cents(value):
        return int((Decimal(str(value)) * 100).quantize(Decimal("1")))
    market = {"0": "trading", "1": "suspended"}.get(row["is_susp_sec"], "unknown")
    if raw is not None and raw.market_state != "unknown" and market != "unknown":
        if raw.market_state != market:
            raise ValueError("raw 与 SDK 停牌状态冲突")
    return {"market_state": market,
            "st_known": row["is_st_sec"] in ("0", "1"),
            "reference_known": _positive(row["preclose"]),
            "limit_known": known,
            "limit_up": bool(known and cents(opening) >= cents(upper)),
            "limit_down": bool(known and cents(opening) <= cents(lower)),
            "absolute_limit_up_price": upper if bounds else None,
            "absolute_limit_down_price": lower if bounds else None}


def build_execution_state_mapping(state_path, *, expected_sha256, calendar,
                                  raw_records, source_audit, evidence_path=None,
                                  state_output_path=None):
    """原表只读；逐字段派生证据可流式外置，缺键保持局部 unknown。"""
    actual = file_sha256(state_path, expected_sha256)
    parquet = pq.ParquetFile(state_path)
    required = set(_FIELDS) | {"code", "date", "row_hash", "source_file_rel",
                                "source_sha256", "sha_origin", "window"}
    if not required <= set(parquet.schema_arrow.names):
        raise ValueError("canonical schema 缺字段")
    states, evidence, seen, pending = {}, [], set(), []
    days = set(calendar)
    with ExitStack() as stack:
        sink = stack.enter_context(Path(evidence_path).open("w", encoding="utf-8")) if evidence_path else None
        for batch in parquet.iter_batches(batch_size=4096):
            for row in batch.to_pylist():
                key = row["code"], row["date"]
                if key in seen or row["market_code"] != row["code"]:
                    raise ValueError("canonical 重复键或代码身份冲突")
                seen.add(key)
                if row["trade_date_str"] != row["date"].strftime("%Y%m%d"):
                    raise ValueError("canonical 日期身份冲突")
                if canonical_row_hash(row) != row["row_hash"]:
                    raise ValueError("canonical row_hash 不匹配")
                source = source_audit.get(row["source_file_rel"])
                if source != (row["source_sha256"], row["sha_origin"]):
                    raise ValueError("source_sha256 未绑定 scope_manifest/probe_result")
                if row["date"] not in days:
                    continue
                state = derive_execution_state(row, raw_records.get(key))
                if state_output_path:
                    pending.append({"code": key[0], "date": key[1], **state})
                    if len(pending) >= 4096:
                        _append_state_batch(state_output_path, pending)
                        pending.clear()
                else:
                    states[key] = state
                proof = {"canonical_sha256": actual, "mapping_version": "sdk_absolute_v1",
                         "raw": row, "derived": state,
                         "semantics": "SDK当日参考及绝对界；WD/XR不推退市或权益；盘前known_at未知"}
                if sink:
                    sink.write(json.dumps(proof, ensure_ascii=False, default=str) + "\n")
                else:
                    evidence.append(proof)
    if state_output_path and pending:
        _append_state_batch(state_output_path, pending)
    return states if not state_output_path else StateLookup(state_output_path), evidence


def _append_state_batch(path, rows):
    table = pa.Table.from_pylist(rows)
    target = Path(path)
    target.mkdir(exist_ok=True)
    index = len(list(target.glob("state_*.parquet")))
    pq.write_table(table, target / f"state_{index:05d}.parquet", compression="zstd")


class StateLookup(Mapping):
    """按代码懒加载SDK派生状态；内存中只保留当前代码。"""
    def __init__(self, path):
        self.path, self._code, self._rows = Path(path), None, {}

    def get(self, key, default=None):
        code = key[0]
        if self._code != code:
            table = pq.read_table(self.path, filters=[("code", "==", code)])
            self._rows = {(row.pop("code"), row.pop("date")): row for row in table.to_pylist()}
            self._code = code
        return self._rows.get(key, default)

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __iter__(self):
        for path in sorted(self.path.glob("state_*.parquet")):
            for batch in pq.ParquetFile(path).iter_batches(columns=["code", "date"]):
                for row in batch.to_pylist():
                    yield row["code"], row["date"]

    def __len__(self):
        return sum(pq.read_metadata(path).num_rows for path in self.path.glob("state_*.parquet"))


class RawRecordLookup:
    """按代码从窗口化本地Parquet懒加载原始行情记录。"""
    def __init__(self, root, first, last):
        self.root, self.first, self.last = Path(root), first, last
        self._code, self._rows = None, {}

    def get(self, key, default=None):
        code, day = key
        if self._code != code:
            path = self.root / f"{code}.parquet"
            if not path.exists():
                return default
            window = read_raw_market_inputs(path, instrument_id=code,
                signal_start=self.first, signal_end=self.last, execution_end=self.last,
                history_bars=21, allow_empty_window=True)
            self._rows = {row.trading_date: row for row in window.records}
            self._code = code
        return self._rows.get(day, default)


class PreparedFeeResolver:
    """按实际成交日惰性解析冻结费用，不物化百万行日码费率表。"""
    def __init__(self, base):
        self.base = base
        self.source_rows = []

    def __getitem__(self, key):
        day, code = key
        fee = _historical_fee(self.base, day, code)
        self.source_rows.append({"date": day.isoformat(), "code": code,
                                 "cost_config": fee.model_dump(mode="json")})
        return fee


def _source_lookup(root, artifacts):
    root = Path(root)
    scope_path = root / "scope_manifest.json"
    scope = _json(scope_path)
    artifacts[str(scope_path)] = file_sha256(scope_path)
    lookup = {}
    for entry in scope["缓存处理"]:
        code = entry["代码"]
        for item in entry["输出"]:
            relative = f"cached_raw/{item['窗口']}_{code.replace('.', '_')}.parquet"
            lookup[relative] = (item["SHA256"], "cache_manifest")
    for path in sorted((root / "batches").glob("batch_*/probe_result.json")):
        artifacts[str(path)] = file_sha256(path)
        for response in _json(path)["响应"]:
            for item in response.get("逐码", []):
                if item.get("SHA256"):
                    name = f"{response['窗口']}_{item['代码'].replace('.', '_')}.parquet"
                    relative = (path.parent / "raw" / name).relative_to(root).as_posix()
                    lookup[relative] = (item["SHA256"], "probe_result")
    return lookup


def _quantity_resolver(config, artifacts):
    rules = {}
    for item in config.get("quantity_evidence", []):
        artifacts[item["path"]] = file_sha256(item["path"], item["sha256"])
    for board in config["quantity_sources"]:
        for key in ("artifact", "corrections", "metadata"):
            path, sha = board[f"{key}_path"], board[f"{key}_sha256"]
            artifacts[path] = file_sha256(path, sha)
        metadata = {r["market_code"]: r for r in _json(board["metadata_path"])["rows"]}
        expected = {"科创板": (200, 1, 100000), "主板": (100, 100, 1000000),
                    "创业板": (100, 100, 300000)}.get(board["metadata_board"])
        if expected != (board["minimum"], board["step"], board["maximum"]):
            raise ValueError("板别数量参数与已核历史规则不一致")
        start = date.fromisoformat(board["supported_from"])
        end = date.fromisoformat(board["supported_through"])
        rule = QuantityRule(board["minimum"], board["step"], board["maximum"],
                            board["source_id"], start, end)
        for code in board["codes"]:
            row = metadata.get(code, {})
            if (code in rules or not code.endswith(board["exchange_suffix"])
                    or row.get("listplate_name") != board["metadata_board"]):
                raise ValueError("板别代码重复或证券类别未经核对")
            rules[code] = (start, end, rule)
    return MappingQuantityRuleResolver(rules)


@dataclass(frozen=True)
class PreparedWindow:
    window: WindowDefinition
    source_id: str
    signal_path: str
    signal_sha256: str
    checkpoint_sha256: str
    signal_rows: Any
    rankings: Any
    coverage: Any
    content_sha256: str
    fee_table: Any = None
    fee_rows: Any = None
    closed_gates: tuple[str, ...] = ()
    sources_sha256: str = ""
    fee_source: Any = None

    def validate(self, window, config, signal_path):
        if (window != self.window or config.source_id != self.source_id or
                config.signal_file_sha256 != self.signal_sha256 or
                config.checkpoint_sha256 != self.checkpoint_sha256 or
                Path(signal_path).resolve() != Path(self.signal_path).resolve()):
            raise ValueError("prepared 输入来源或日期跨窗身份冲突")
        if _signal_content_fingerprint(self.signal_rows) != self.content_sha256:
            raise ValueError("prepared 信号内容指纹冲突")


def _window_inputs(name, spec, calendar, prereg, artifacts):
    anchor, end = date.fromisoformat(spec["anchor"]), date.fromisoformat(spec["evaluation_end"])
    buffer = tuple(map(date.fromisoformat, spec["buffer_dates"]))
    dates = tuple(day for day in calendar if anchor <= day <= buffer[-1])
    window = WindowDefinition(anchor, end, dates)
    registered = prereg["窗口"][name]
    if (spec["anchor"] != registered["anchor"] or spec["evaluation_end"] != registered["end"]
            or spec["buffer_dates"] != registered["buffer"] or window.buffer_dates != buffer
            or len(window.signal_dates) != registered["decision_days"]):
        raise ValueError("窗口日期与预注册冲突")
    for key in ("signal_metadata", "checkpoint"):
        artifacts[spec[f"{key}_path"]] = file_sha256(
            spec[f"{key}_path"], spec[f"{key}_sha256"])
    metadata = _json(spec["signal_metadata_path"])
    artifacts[spec["config_path"]] = file_sha256(spec["config_path"], spec["config_sha256"])
    artifacts[spec["checkpoint_verification_path"]] = file_sha256(
        spec["checkpoint_verification_path"], spec["checkpoint_verification_sha256"])
    if (metadata.get("feature_cols") != ["open", "high", "low", "close"] or
            metadata.get("normalize") != "relative" or metadata.get("label_mode") != "excess" or
            metadata.get("seq_len") != 60 or metadata.get("horizon") != 10):
        raise ValueError("冻结F4信号语义与配置不一致")
    for key in ("checkpoint_sha256", "config_sha256"):
        if metadata[key] != spec[key]:
            raise ValueError(f"信号 metadata {key} 冲突")
    if metadata["decision_calendar"] != [day.isoformat() for day in window.signal_dates]:
        raise ValueError("信号 metadata 日历冲突")
    return window


def _lifecycle_metadata(config):
    path = config["quantity_sources"][0]["metadata_path"]
    return {r["market_code"]: r for r in _json(path)["rows"]}


def _absence_reason(config, metadata, code, day):
    row = metadata.get(code, {})
    numeric = int(day.strftime("%Y%m%d"))
    if row.get("listdate") and numeric < row["listdate"]:
        return "pre_listing"
    if row.get("delistdate") and numeric > row["delistdate"]:
        return "post_delisting"
    for interval in config.get("pause_intervals", []):
        if (code == interval["code"] and interval["start"] <= str(day) < interval["end"]):
            return "official_pause_interval"
    return "unexplained"


def _empty_codes(config, codes, days):
    metadata = _lifecycle_metadata(config)
    return frozenset(code for code in codes if all(
        _absence_reason(config, metadata, code, day) != "unexplained" for day in days))


def _gap_coverage(config, out, artifacts):
    for interval in config.get("pause_intervals", []):
        for item in interval["evidence"]:
            artifacts[item["path"]] = file_sha256(item["path"], item["sha256"])
    metadata, counts = _lifecycle_metadata(config), {}
    with (out / "gap_coverage.jsonl").open("w", encoding="utf-8") as stream:
        for batch in pq.ParquetFile(config["gap_index_path"]).iter_batches():
            for row in batch.to_pylist():
                day = date.fromisoformat(row["date"])
                reason = _absence_reason(config, metadata, row["code"], day)
                counts[reason] = counts.get(reason, 0) + 1
                stream.write(json.dumps({**row, "explanation": reason}, ensure_ascii=False) + "\n")
    _save(out / "gap_summary.json", counts)


def _raw_cache(config, windows, codes, out, artifacts):
    """所有代码只扫描一次Z；保留共同本地原价缓存，随后各窗严格截止。"""
    first = min(w.anchor_date for w in windows.values())
    last = max(w.execution_calendar[-1] for w in windows.values())
    root = Path(config["raw_market_root"])
    cache = out / "raw"
    cache.mkdir(exist_ok=True)
    stats = []
    explanations = _empty_codes(config, codes, {d for w in windows.values() for d in w.signal_dates})
    total = len(codes)
    for idx, code in enumerate(codes, 1):
        print(f"DIAG: raw_cache {idx}/{total} {code}", flush=True)
        path = root / f"{code}.parquet"
        started = perf_counter()
        try:
            source_sha = file_sha256(path)
            footer = pq.ParquetFile(path)
            scan_statistics = {}
            window = read_raw_market_inputs(path, instrument_id=code, signal_start=first,
                signal_end=last, execution_end=last, history_bars=21,
                allow_empty_window=code in explanations, read_statistics=scan_statistics)
            rows = []
            for row in window.records:
                rows.append({"code": code, "kline_time": datetime.combine(row.trading_date, time()),
                    "open": row.open, "high": row.high, "low": row.low, "close": row.close,
                    "volume": row.source_volume, "amount": row.source_amount,
                    "is_trading": (True if row.market_state == "trading" else
                                   False if row.market_state == "suspended" else None)})
            schema = pa.schema([("code", pa.string()), ("kline_time", pa.timestamp("us")),
                *[(key, pa.float64()) for key in ("open", "high", "low", "close")],
                ("volume", pa.int64()), ("amount", pa.float64()), ("is_trading", pa.bool_())])
            target = cache / f"{code}.parquet"
            pq.write_table(pa.Table.from_pylist(rows, schema=schema), target)
            artifacts[str(target)] = file_sha256(target)
            stats.append({"code": code, "source": str(path), "source_size": path.stat().st_size,
                           "source_bytes": path.stat().st_size, **scan_statistics,
                          "source_sha256": source_sha, "row_groups": footer.num_row_groups,
                          "source_rows": footer.metadata.num_rows, "retained_rows": len(rows),
                          "seconds": perf_counter() - started})
            del window, rows, footer
            gc.collect()
            pa.default_memory_pool().release_unused()
        except Exception as exc:
            print(f"DIAG: raw_cache CRASH at {code}: {type(exc).__name__}: {exc}", flush=True)
            raise
    _save(out / "raw_read_statistics.json", stats)
    return cache


def prepare_staged_inputs(config_path, output_dir):
    """排他准备两窗共同缓存；不启动绩效、不加载训练源或模型。"""
    config = _json(config_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    artifacts = {str(Path(config_path).resolve()): file_sha256(config_path)}
    for key in ("preregistration", "calendar_csv", "index", "state", "gap_index", "state_audit"):
        artifacts[config[f"{key}_path"]] = file_sha256(
            config[f"{key}_path"], config[f"{key}_sha256"])
    prereg = _json(config["preregistration_path"])
    if (config["initial_capital"] != 1_000_000 or config["policies"] != ["B1", "S1", "S2", "C70"]
            or set(config["windows"]) != {"W1", "W2"}
            or config["strict_tax"] is not False or config["tax_policy"] != "cash_dividend_20pct_stress"):
        raise ValueError("资金、策略、窗口或探索税务配置与预注册冲突")
    calendar, benchmark = [], {}
    with Path(config["calendar_csv_path"]).open(encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            day = date.fromisoformat(row["date"])
            if day in benchmark or not _positive(float(row["benchmark_close"])):
                raise ValueError("日历重复或基准无效")
            calendar.append(day)
            benchmark[day] = float(row["benchmark_close"])
    if calendar != sorted(calendar):
        raise ValueError("日历未递增")
    _verify_index(config["index_path"], benchmark)
    windows = {name: _window_inputs(name, spec, calendar, prereg, artifacts)
               for name, spec in config["windows"].items()}
    snapshot = load_corporate_action_snapshot(config["ca_root"],
        manifest_path=config["ca_manifest_path"], expected_manifest_sha256=config["ca_manifest_sha256"])
    artifacts[config["ca_manifest_path"]] = snapshot.manifest_sha256
    for relative, sha in snapshot.file_sha256.items():
        artifacts[str(Path(config["ca_root"]) / relative)] = sha
    _quantity_resolver(config, artifacts)
    audit = _json(config["state_audit_path"])
    if audit["规范表SHA256"] != config["state_sha256"]:
        raise ValueError("状态核验报告与 canonical 摘要不一致")
    codes = set()
    for name, spec in config["windows"].items():
        codes.update(_prepare_signal(name, spec, windows[name], out, artifacts))
        gc.collect()
        pa.default_memory_pool().release_unused()
    return _finish_preparation(config, out, artifacts, windows, benchmark, codes, snapshot)


def _verify_index(path, benchmark):
    seen = set()
    for batch in pq.ParquetFile(path).iter_batches(columns=["code", "kline_time", "close"]):
        for row in batch.to_pylist():
            day = row["kline_time"].date()
            if day not in benchmark:
                continue
            if day in seen or row["code"] != "000300.SH" or abs(row["close"] - benchmark[day]) > 1e-8:
                raise ValueError("指数与冻结日历基准不一致")
            seen.add(day)
    if seen != set(benchmark):
        raise ValueError("指数缺冻结基准日期")


def _prepare_signal(name, spec, window, out, artifacts):
    target = out / f"signal_{name}.parquet"
    target.write_bytes(Path(spec["signal_path"]).read_bytes())
    rows, actual = load_frozen_signal_parquet(target, spec["signal_sha256"])
    if set(rows) != set(window.signal_dates):
        raise ValueError("信号日期跨窗冲突")
    build_signal_ranking(spec["source_id"], rows)
    artifacts[spec["signal_path"]] = actual
    # 保存冻结原列，true_ret保持原值；不读取标签或训练大源。
    artifacts[str(target)] = actual
    (out / f"calendar_{name}.txt").write_text(
        "\n".join(day.isoformat() for day in window.execution_calendar) + "\n", encoding="utf-8")
    return {row["instrument_id"] for day_rows in rows.values() for row in day_rows}


def _provider(cache, window, records, states, snapshot, *, allow_empty=frozenset()):
    ca_dates = frozenset((item.instrument_id, item.event.ex_date) for item in
                         snapshot.descriptors if item.event is not None)
    market = CnnRawMarketDataProvider(cache, signal_start=window.signal_dates[0],
        signal_end=window.evaluation_end, execution_end=window.execution_calendar[-1],
        history_bars=21, verified_states=states, corporate_action_dates=ca_dates,
        allow_empty_window=allow_empty)
    for (code, day), row in records.items():
        if day <= window.execution_calendar[-1]:
            market._records.setdefault(code, {})[day] = row
    return market


def _finish_preparation(config, out, artifacts, windows, benchmark, codes, snapshot):
    started = perf_counter()
    _gap_coverage(config, out, artifacts)
    cache = _raw_cache(config, windows, sorted(codes), out, artifacts)
    source_audit = _source_lookup(config["state_source_root"], artifacts)
    raw_lookup = RawRecordLookup(cache, min(w.anchor_date for w in windows.values()),
                                 max(w.execution_calendar[-1] for w in windows.values()))
    states, _ = build_execution_state_mapping(config["state_path"],
        expected_sha256=config["state_sha256"], calendar=benchmark,
        raw_records=raw_lookup, source_audit=source_audit,
        evidence_path=out / "state_mapping_evidence.jsonl",
        state_output_path=out / "states")
    cost = _frozen_cost(config)
    for name, window in windows.items():
        signals, _ = load_frozen_signal_parquet(
            out / f"signal_{name}.parquet", config["windows"][name]["signal_sha256"])
        # 按窗计算空代码集：某窗所有信号日都在暂停/退市期间内的代码
        window_codes = {r["instrument_id"] for day_rows in signals.values() for r in day_rows}
        window_empty = _empty_codes(config, window_codes, frozenset(window.signal_dates))
        market = _provider(cache, window, {}, states, snapshot, allow_empty=window_empty)
        local_codes = sorted(window_codes)
        ranking = build_signal_ranking(config["windows"][name]["source_id"], signals)
        keep_keys = set()
        eligible_codes = {code for ranked in ranking.values() for code in ranked.ranks
                          if ranked.ranks[code] <= 5 and ranked.buy_eligible[code]}
        keep_keys.update((code, day) for code in eligible_codes for day in window.execution_calendar)
        for day, ranked in ranking.items():
            next_day = window.execution_calendar[window.execution_calendar.index(day) + 1]
            keep_keys.update((code, day) for code, rank in ranked.ranks.items() if rank <= 5)
            keep_keys.update((code, next_day) for code, rank in ranked.ranks.items()
                             if rank <= 5 and ranked.buy_eligible[code])
        coverage_path = out / f"market_coverage_{name}.jsonl"
        coverage = _market_coverage(market, local_codes, window.execution_calendar,
            keep_keys=keep_keys, stream_path=coverage_path)
        coverage["shared_path"] = str(coverage_path)
        coverage["shared_sha256"] = file_sha256(coverage_path)
        _save(out / f"coverage_{name}.json", coverage)
        fee_source = {"source": "historical_costs.resolve_historical_costs",
                      "calendar_dates": len(window.execution_calendar) - 1,
                      "universe_codes": len(local_codes), "precomputed_rows": 0,
                      "base_config": cost.model_dump(mode="json")}
        _save(out / f"fees_{name}.json", fee_source)
        del signals, market, ranking, keep_keys, eligible_codes, coverage
        gc.collect()
        pa.default_memory_pool().release_unused()
    _save(out / "integration_inputs.json", config)
    for path in out.rglob("*"):
        if path.is_file():
            artifacts[str(path)] = file_sha256(path)
    core_path = Path(inspect.getfile(run_account_backtest_from_orders))
    manifest = {"schema_version": "staged_prepared_v1", "config": config,
                "raw_cache": str(cache), "output_dir": str(out), "artifacts": artifacts,
                "core_path": str(core_path), "core_sha256": file_sha256(core_path),
                "benchmark": {str(k): v for k, v in benchmark.items()},
                "preparation_seconds": perf_counter() - started,
                "actual_after_tax_target_eligible": False}
    _save(out / "manifest.json", manifest)
    (out / "manifest.sha256").write_text(file_sha256(out / "manifest.json"), encoding="ascii")
    return out / "manifest.json"


def _frozen_cost(config):
    expected = CostConfig(commission_rate=.0002, commission_rate_buy=.0002,
        commission_rate_sell=.0002, min_commission=5, stamp_tax_rate=.001,
        transfer_fee_rate=.00002, impact_coefficient=1, adv_window=20, sigma_window=20,
        sigma_clip=(.005, .08), p_cap=.10, spread_floor=.0002, slip_max=.05,
        missing_volume_policy="warn")
    cost = CostConfig(**config["cost_config"])
    if cost != expected:
        raise ValueError("费用与预注册冻结参数不一致")
    return cost


def _historical_fee(cost, day, code):
    if not code.endswith((".SH", ".SZ")):
        raise ValueError("未核对沪深A股费用类别")
    return resolve_historical_costs(execution_date=day,
        market="SSE_A" if code.endswith(".SH") else "SZSE_A", commission=cost)


def _load_prepared_window(manifest, name, snapshot):
    config, root = manifest["config"], Path(manifest["output_dir"])
    spec = config["windows"][name]
    calendar = tuple(date.fromisoformat(d) for d in (root / f"calendar_{name}.txt").read_text().splitlines())
    window = WindowDefinition(date.fromisoformat(spec["anchor"]),
                              date.fromisoformat(spec["evaluation_end"]), calendar)
    signal_path = root / f"signal_{name}.parquet"
    rows, sha = load_frozen_signal_parquet(signal_path, spec["signal_sha256"])
    rankings = MappingProxyType(build_signal_ranking(spec["source_id"], rows))
    frozen_rows = MappingProxyType({d: tuple(MappingProxyType(r) for r in rs) for d, rs in rows.items()})
    states = StateLookup(root / "states")
    market = CnnRawMarketDataProvider(manifest["raw_cache"], signal_start=window.signal_dates[0],
        signal_end=window.evaluation_end, execution_end=calendar[-1], history_bars=21,
        verified_states=states, corporate_action_dates=frozenset(
            (i.instrument_id, i.event.ex_date) for i in snapshot.descriptors if i.event is not None),
        allow_empty_window=_empty_codes(config,
            {r["instrument_id"] for rs in rows.values() for r in rs}, window.signal_dates))
    return _complete_prepared_window(root, name, window, spec, signal_path, sha,
                                     frozen_rows, rankings, market)


def _complete_prepared_window(root, name, window, spec, signal_path, sha, rows, rankings, market):
    coverage_path = root / f"coverage_{name}.json"
    coverage = _json(coverage_path)
    coverage["shared_path"] = str(coverage_path)
    coverage["shared_sha256"] = file_sha256(coverage_path)
    fee_source = _json(root / f"fees_{name}.json")
    fees = PreparedFeeResolver(CostConfig(**fee_source["base_config"]))
    prepared = PreparedWindow(window, spec["source_id"], str(signal_path), sha,
        spec["checkpoint_sha256"], rows, rankings, coverage,
        _signal_content_fingerprint(rows), fees,
        [],
        ("authoritative_calendar_not_accepted", "checkpoint_artifact_not_verified",
         "market_source_lineage_not_accepted"), file_sha256(root / "manifest.json"),
        {"shared_path": str(root / f"fees_{name}.json"),
         "sha256": file_sha256(root / f"fees_{name}.json")})
    return prepared, market


def _verify_prepared(path):
    path = Path(path)
    file_sha256(path, path.with_suffix(".sha256").read_text(encoding="ascii").strip())
    manifest = _json(path)
    for artifact, sha in manifest["artifacts"].items():
        file_sha256(artifact, sha)
    core = Path(inspect.getfile(run_account_backtest_from_orders))
    file_sha256(core, manifest["core_sha256"])
    if str(core) != manifest["core_path"]:
        raise ValueError("实际 core import 路径改变")
    return manifest


def run_prepared_windows(prepared_manifest_path, run_root, research_mode="exploration"):
    """共享输入先验核对一次；八次独立账户尝试，失败不阻断后续窗口。"""
    manifest = _verify_prepared(prepared_manifest_path)
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=False)
    config, artifacts, outcomes = manifest["config"], {}, []
    quantity = _quantity_resolver(config, artifacts)
    snapshot = load_corporate_action_snapshot(config["ca_root"],
        manifest_path=config["ca_manifest_path"], expected_manifest_sha256=config["ca_manifest_sha256"])
    cost = _frozen_cost(config)
    for name in ("W1", "W2"):
        prepared, market = _load_prepared_window(manifest, name, snapshot)
        for policy in ("B1", "S1", "S2", "C70"):
            outcomes.append(_run_candidate(root, name, policy, config, prepared,
                market, snapshot, quantity, cost, research_mode, manifest))
    comparisons = []
    for name in ("W1", "W2"):
        rows = {r["policy"]: r for r in outcomes if r["window"] == name}
        for left, right in (("S2", "B1"), ("S1", "S2"), ("C70", "B1")):
            a, b = rows[left].get("main_return"), rows[right].get("main_return")
            comparisons.append({"window": name, "comparison": f"{left}-{right}",
                                "difference": None if a is None or b is None else a - b})
    _save(root / "summary.json", {"attempts": outcomes, "comparisons": comparisons,
                                  "actual_after_tax_target_eligible": False})
    (root / "summary.sha256").write_text(file_sha256(root / "summary.json"), encoding="ascii")
    return root / "summary.json"


def _run_candidate(root, name, policy, config, prepared, market, snapshot,
                   quantity, cost, research_mode, manifest):
    if research_mode not in ("exploration", "strict"):
        raise ValueError("研究模式必须显式为exploration或strict")
    out = root / f"{name}_{policy}"
    cfg = StagedWindowConfig(source_id=prepared.source_id,
        signal_file_sha256=prepared.signal_sha256, checkpoint_sha256=prepared.checkpoint_sha256,
        initial_capital=config["initial_capital"], policy=Policy(policy),
        tax_policy=config["tax_policy"], cost_config=cost, period_id=name,
        require_known_share_tax=research_mode == "strict")
    summary = {"window": name, "policy": policy, "output_dir": str(out),
               "actual_after_tax_target_eligible": False}
    try:
        outcome = run_staged_window(window=prepared.window, config=cfg,
            signal_parquet_path=prepared.signal_path, market=market,
            corporate_action_snapshot=snapshot, quantity_rule_resolver=quantity,
            prepared_inputs=prepared, output_dir=out)
        benchmark = manifest["benchmark"]
        w = prepared.window
        benchmark_return = benchmark[str(w.evaluation_end)] / benchmark[str(w.anchor_date)] - 1
        value = float(outcome.provenance["main_nav_end"]) / config["initial_capital"] - 1
        summary.update(mechanical_status=outcome.mechanical_status, main_return=value,
            benchmark_return=benchmark_return, numerical_target=value >= 0 and value > benchmark_return,
            production_acceptance=outcome.production_acceptance,
            buffer_return=outcome.provenance.get("buffer_return"),
            buffer_benchmark_return=benchmark[str(w.buffer_dates[-1])] / benchmark[str(w.evaluation_end)] - 1,
            config_hash=outcome.config_hash, input_manifest_sha256=prepared.sources_sha256,
            validation_failures=list(outcome.validation_failures))
    except Exception as error:  # noqa: BLE001
        summary.update(mechanical_status="INCOMPLETE", error_type=type(error).__name__,
                       error=str(error))
        if not out.exists():
            out.mkdir()
        _save(out / "batch_error.json", summary)
    finally:
        _save(out / "sources_manifest.json", {"artifacts": manifest["artifacts"],
            "core_path": manifest["core_path"], "core_sha256": manifest["core_sha256"]})
        _save(out / "artifacts.json", {p.name: file_sha256(p) for p in out.iterdir()
                                      if p.is_file() and p.name != "artifacts.json"})
    return summary


def run_single_from_cli(args, window):
    config = _json(args.input_config)
    matches = [(name, s) for name, s in config["windows"].items() if s["source_id"] == args.source_id]
    if len(matches) != 1:
        raise ValueError("CLI来源未唯一匹配配置")
    name, spec = matches[0]
    if (Path(args.signal_parquet).resolve() != Path(spec["signal_path"]).resolve()
            or args.expected_sha256 != spec["signal_sha256"]
            or args.checkpoint_sha256 != spec["checkpoint_sha256"]
            or str(args.anchor_date) != spec["anchor"] or str(args.evaluation_end) != spec["evaluation_end"]
            or args.initial_capital != config["initial_capital"] or args.tax_policy != config["tax_policy"]
            or args.lot_size != 100 or args.tick_size != .01):
        raise ValueError("CLI参数与冻结输入配置冲突")
    manifest_path = args.prepared_manifest
    if not manifest_path:
        manifest_path = prepare_staged_inputs(args.input_config, str(Path(args.output_dir)) + "_prepared")
    manifest = _verify_prepared(manifest_path)
    if manifest["config"] != config:
        raise ValueError("prepared配置与CLI配置冲突")
    snapshot = load_corporate_action_snapshot(config["ca_root"], manifest_path=config["ca_manifest_path"],
        expected_manifest_sha256=config["ca_manifest_sha256"])
    prepared, market = _load_prepared_window(manifest, name, snapshot)
    if prepared.window.execution_calendar != window.execution_calendar:
        raise ValueError("CLI日历与准备窗口冲突")
    cfg = StagedWindowConfig(source_id=spec["source_id"], signal_file_sha256=spec["signal_sha256"],
        checkpoint_sha256=spec["checkpoint_sha256"], initial_capital=config["initial_capital"],
        policy=Policy(args.policy), tax_policy=config["tax_policy"], cost_config=_frozen_cost(config),
        period_id=name, require_known_share_tax=args.research_mode == "strict")
    return run_staged_window(window=prepared.window, config=cfg, signal_parquet_path=prepared.signal_path,
        market=market, corporate_action_snapshot=snapshot, quantity_rule_resolver=_quantity_resolver(config, {}),
        prepared_inputs=prepared, output_dir=args.output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="冻结输入准备与独立八窗研究")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--run-prepared", action="store_true")
    parser.add_argument("--config")
    parser.add_argument("--prepare-dir")
    parser.add_argument("--prepared-manifest")
    parser.add_argument("--run-root")
    parser.add_argument("--research-mode", choices=["exploration", "strict"], default="exploration")
    args = parser.parse_args(argv)
    if args.prepare_only:
        if not args.config or not args.prepare_dir or args.prepared_manifest or args.run_root:
            parser.error("prepare-only要求config/prepare-dir，不能混入run参数")
        print(prepare_staged_inputs(args.config, args.prepare_dir))
    else:
        if not args.prepared_manifest or not args.run_root or args.config or args.prepare_dir:
            parser.error("run-prepared要求prepared-manifest/run-root，不能混入prepare参数")
        print(run_prepared_windows(args.prepared_manifest, args.run_root, args.research_mode))


if __name__ == "__main__":
    main()
