"""2025 受限条件研究入口；原 core 是唯一账户账本。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime
from datetime import time as clock_time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
# 证据根默认仍是原位置（ROOT.parent）；W1 树已退役，主区可用
# CNN_2025_EVIDENCE_ROOT 显式注入外部证据根，不改变任何校验强度。
EVIDENCE_ROOT_ENV = "CNN_2025_EVIDENCE_ROOT"
TEMP = Path(os.environ[EVIDENCE_ROOT_ENV]) if os.environ.get(EVIDENCE_ROOT_ENV) else ROOT.parent
DELIVERY = TEMP / "validation_2025_restricted_delivery_20261029"
REVIEWED = TEMP / "corporate-action-fix-20261027"
REVIEW_HASHES = TEMP / "staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json"
ANCHOR, FIRST_SIGNAL, END = date(2024, 12, 31), date(2025, 1, 2), date(2025, 12, 16)
HDF_MAPPING = {"MARKET_CODE": "market_code", "TRADE_DATE": "trade_date_str", "PRECLOSE": "preclose",
    "HIGH_LIMITED": "high_limited", "LOW_LIMITED": "low_limited", "PRICE_HIGH_LMT_RATE": "high_lmt_rate",
    "PRICE_LOW_LMT_RATE": "low_lmt_rate", "IS_ST_SEC": "is_st_sec", "IS_SUSP_SEC": "is_susp_sec",
    "IS_WD_SEC": "is_wd_sec", "IS_XR_SEC": "is_xr_sec"}


def sha(path, expected=None):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"原始字节 SHA 不匹配：{path}")
    return digest


def verify_reviewed(*, reviewed_root=None, hashes_path=None):
    """校验既审16文件；默认路径缺失或字节不符即 fail-closed，不提供降级通道。"""
    _assert_clean_interpreter()
    root = REVIEWED if reviewed_root is None else Path(reviewed_root)
    manifest = REVIEW_HASHES if hashes_path is None else Path(hashes_path)
    hashes = json.loads(manifest.read_text(encoding="utf-8"))
    if len(hashes) != 16:
        raise ValueError("既审文件清单必须为16项")
    return {str(root / name): sha(root / name, value) for name, value in hashes.items()}


_REVIEW_IDENTITY = None


def review_identity():
    """延迟校验既审身份并缓存：模块 import 不触发，真实研究入口仍 fail-closed。"""
    global _REVIEW_IDENTITY
    if _REVIEW_IDENTITY is None:
        _REVIEW_IDENTITY = verify_reviewed()
    return _REVIEW_IDENTITY


def review_identity_available():
    """只读探测既审身份能否复验；失败只返回 False，绝不降级门禁。"""
    if _REVIEW_IDENTITY is not None:
        return True
    try:
        review_identity()
    except (OSError, ValueError, KeyError, RuntimeError):
        return False
    return True


# 解释器污染只在 import 期记录，不再直接抛错：整包同进程收集（如 pytest）时
# 其它测试模块可能先导入主区 backtest；真正的隔离门在研究入口处强制执行。
_BACKTEST_PREIMPORTED = any(name == "backtest" or name.startswith("backtest.") for name in sys.modules)


def _assert_clean_interpreter():
    """研究入口硬门：解释器已混入其它 backtest 树时拒绝，避免静默用错树。"""
    if _BACKTEST_PREIMPORTED:
        raise RuntimeError("须在干净解释器先导入受限入口，禁止混合不同树的 backtest 模块")


# 注意：历史上的模块级"干净解释器"硬校验已延迟到 _assert_clean_interpreter()，
# 由 verify_reviewed() 在每个真实研究入口处强制执行；import 期只记录不抛错，
# 否则整包同进程收集（如 pytest）时其它测试模块先导入主区 backtest 会导致导入即崩。
sys.path.insert(0, str(REVIEWED))

# 本导入块必须位于 sys.path.insert(REVIEWED) 之后，否则会先导入主区 backtest.*；
# 故不能按 isort 默认规则上移排序（W1 树原貌）。
import numpy as np  # noqa: I001
import pyarrow as pa
import pyarrow.parquet as pq
from backtest.cnn_adapter.ca.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.ca.corporate_action_snapshot_loader import (
    CorporateActionSnapshot,
    descriptor_from_row,
    load_corporate_action_snapshot,
)
from backtest.cnn_adapter.quantity_rules import QuantityRule, QuantityRuleError
from backtest.cnn_adapter.staged_candidate_runner import (
    StagedWindowConfig,
    StagedWindowOutcome,
    WindowDefinition,
    _config_hash,
    _freeze_fees,
    _full_rank_rows,
    _market_coverage,
    _plain,
    _RecordingObserver,
    _RecordingStrategy,
    _signal_content_fingerprint,
    _write_final_audit,
    _write_outputs,
    build_signal_ranking,
)
from backtest.cnn_adapter.staged_production_inputs import RawRecordLookup, canonical_row_hash, derive_execution_state
from backtest_core.contracts.account_actions import RecordPosition
from backtest_core.contracts.config import CostConfig, ExecutionConfig, PortfolioConfig
from backtest_core.contracts.enums import Side
from backtest_core.engine import run_account_backtest_from_orders
from backtest_core.testing.synthetic import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.historical_costs import resolve_historical_costs
from backtest.cnn_adapter.ca.raw_market_provider import CnnRawMarketDataProvider
from backtest.cnn_adapter.staged_allocation import AllocationRegistry, Policy
from backtest.cnn_adapter.staged_execution_bridge import StagedExecutionBridge
from backtest.cnn_adapter.staged_order_strategy import MappingRankingSource

INPUT_PINS = {
    "validation_2025_bridge_delivery_20261029/DATA_IDENTITY.json":
        "a8f5833146455d193f69fda7e04693fc8be4c3d8778c53ce8c14df3a8e2ed340",
    "validation_2025_local_inputs_20261029/full190/candidate_manifest.json":
        "f3281b5b01d20abd624b4ad08b7d4b967922583361ed0d4c095a49ba91f9fc35",
    "validation_2025_local_inputs_20261029/full190/source_manifest.json":
        "2db3ae17c93688e96c4864fc6807c55900b2f3ee567165720d9964925716f4fc",
    "validation_2025_local_inputs_20261029/raw_ohlcv_full174_v2/candidate_manifest.json":
        "c8c4408b4e05141187fb264cd2cc699418ba3b1703063084afe4d6fcd0d24439",
    "validation_2025_local_inputs_20261029/ca_full174/delivery_manifest_v4.json":
        "0df580761f006f52f9285205e249fa7bb11eb0729ee75ee4d2aecc28a6667f0d",
}
LOCAL_QA_PATH = TEMP / "validation_2025_local_inputs_independent_qa_20261029/INDEPENDENT_QA_REPORT.md"
LOCAL_QA_SHA = "29bd941a17b5f31f46ecbe1e8081d6c5d3f1a566e15e7ff03ece7cfe7818cf82"


def pinned_json(relative):
    path = TEMP / relative
    sha(path, INPUT_PINS[relative])
    return json.loads(path.read_text(encoding="utf-8"))


class DateBoardQuantity:
    """显式日期板别映射；当前文件哈希不等于官方适用性已认证。"""
    def __init__(self, mappings, rules, *, fixture_only=False):
        self.mappings, self.rules, self.fixture_only = mappings, [], fixture_only
        self.artifacts = {}
        self.evidence_metadata = {}
        for mapping in mappings:
            exchange = {"SZSE_MAIN": ".SZ", "SSE_MAIN": ".SH", "CHINEXT": ".SZ", "STAR": ".SH", "BSE": ".BJ"}
            if mapping.get("board") not in exchange:
                raise QuantityRuleError("unknown_board：证券板别必须显式提供")
            if not mapping["code"].endswith(exchange[mapping["board"]]):
                raise QuantityRuleError("board_market_conflict：板别与市场不符")
            self._interval(mapping)
        for row in rules:
            start, end = self._interval(row)
            artifacts = row.get("artifacts", [])
            if not artifacts and not fixture_only:
                raise QuantityRuleError("quantity_evidence_missing：缺规则证据")
            for artifact in artifacts:
                self.artifacts[artifact["path"]] = sha(artifact["path"], artifact["sha256"])
            rule = QuantityRule(row["minimum"], row["step"], row["maximum"], row["source_id"], start, end)
            self.rules.append((row["board"], rule))

    @staticmethod
    def _interval(row):
        start, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
        if start > end:
            raise QuantityRuleError("数量映射适用日期倒置")
        return start, end

    def __call__(self, day, code):
        boards = [m["board"] for m in self.mappings if m["code"] == code
                  and self._interval(m)[0] <= day <= self._interval(m)[1]]
        if len(boards) != 1:
            raise QuantityRuleError("unknown_board_or_date：证券板别未唯一匹配")
        rules = [rule for board, rule in self.rules if board == boards[0]
                 and rule.effective_from <= day <= rule.effective_through]
        if len(rules) != 1:
            raise QuantityRuleError("quantity_rule_date_unknown：规则日期未唯一匹配")
        return rules[0]


def load_quantity_input(path, expected_sha, *, allow_fixture=False):
    sha(path, expected_sha)
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    fixture = payload.get("fixture_only", False)
    if fixture and not allow_fixture:
        raise QuantityRuleError("合成source只允许测试，不可用于真实2025规则闭合")
    if not fixture and any(row.get("tick_size") != .01 for row in payload["board_rule_dates"]):
        raise QuantityRuleError("quantity_tick_unknown：本策略只接受显式0.01价格单位")
    resolver = DateBoardQuantity(payload["code_board_dates"], payload["board_rule_dates"], fixture_only=fixture)
    resolver.evidence_metadata = {key: value for key, value in payload.items()
                                  if key not in ("code_board_dates", "board_rule_dates")}
    return resolver


def fetch_sz_rules(output, *, recorded_404_log=None):
    """下载免费公开官方附件；不把文本原件升级为2025沿革认证。"""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    url = "https://docs.static.szse.cn/www/lawrules/index/rule/W020230217564423808793.pdf"
    content, final_url, download_error = None, url, None
    if recorded_404_log is not None:
        if "HTTP Error 404" not in Path(recorded_404_log).read_text(encoding="utf-8"):
            raise ValueError("复用日志未含404证据")
        download_error = "HTTPError:404；复用既有失败日志，不再请求网络"
    else:
        try:
            with urlopen(url, timeout=30) as response:
                content, final_url = response.read(), response.url
        except (HTTPError, URLError, TimeoutError) as error:
            download_error = f"{type(error).__name__}:{error}"
    if content is not None and (not content.startswith(b"%PDF-") or len(content) < 10000):
        raise ValueError("官方附件响应不是完整PDF")
    pdf = output / "szse_2023_rules.pdf"
    if content is not None:
        pdf.write_bytes(content)
    metadata_path = TEMP / "staged_production_integration_delivery_20261027/security_metadata.json"
    metadata_sha = sha(metadata_path, "742e9a553e4e582fe8400b8970850ef4a92a9f1a24ae01c5b0bf27554f76c5bb")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mappings = []
    for row in metadata["rows"]:
        if row["market_code"].endswith(".SZ") and row["listplate_name"] == "主板" and row.get("listdate"):
            listed = datetime.strptime(str(row["listdate"]), "%Y%m%d").date()
            start = max(date(2025, 1, 1), listed)
            if start <= date(2025, 12, 19):
                mappings.append({"code": row["market_code"], "board": "SZSE_MAIN", "start": str(start),
                                 "end": "2025-12-19"})
    report_path = TEMP / "market_rules_2025_research_20261029/REPORT.md"
    artifacts = [{"path": str(report_path), "sha256": sha(report_path)},
                 {"path": str(metadata_path), "sha256": metadata_sha}]
    if content is not None:
        artifacts.append({"path": str(pdf), "sha256": sha(pdf)})
    if recorded_404_log is not None:
        artifacts.append({"path": str(recorded_404_log), "sha256": sha(recorded_404_log)})
    payload = {"fixture_only": False, "evidence_kind": "conditional_rule_scenario",
        "assumption": "2023深市主板数量/tick规则在2025相应日期适用；非沿革完整性认证",
        "official_url": url, "download_final_url": final_url, "evidence_recorded_at": datetime.now(UTC).isoformat(),
        "download_error": download_error, "official_pdf_sha256": None if content is None else sha(pdf),
        "source_type": "research_report_conditional_assumption", "own_pdf_text_verified": False,
        "historical_amendments_complete": False, "official_2025_confirmed": False, "metadata_pit_verified": False,
        "code_board_dates": mappings, "board_rule_dates": [{"board": "SZSE_MAIN", "start": "2025-01-01",
            "end": "2025-12-19", "minimum": 100, "step": 100, "maximum": 1000000,
            "source_id": "SZSE2023_3.3.8-3.3.12_CONDITIONAL2025", "tick_size": .01, "artifacts": artifacts}]}
    save(output / "conditional_sz_main_2025.json", payload)
    return {"pdf_sha256": None if content is None else sha(pdf), "download_error": download_error,
            "quantity_input_sha256": sha(output / "conditional_sz_main_2025.json")}


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class SparseMarket:
    """明确范围外返回未知，范围内异常透传；不回退 Z provider。"""
    def __init__(self, provider, raw_codes, states):
        self.provider, self.raw_codes, self.verified_states = provider, frozenset(raw_codes), states
        self.missing = set()
        self.execution_guard = False
        self.buy_requests = set()
        self.sell_requests = set()

    def get_bar(self, code, day):
        if code not in self.raw_codes:
            self.missing.add((code, day, "raw_file_missing_or_outside_scope"))
            return None
        bar = self.provider.get_bar(code, day)
        if bar is None:
            self.missing.add((code, day, "raw_day_missing"))
        state = self.verified_states.get((code, day))
        if (self.execution_guard and (code, day) in self.buy_requests
                and state is not None and state.get("is_st_sec") == "1"):
            raise ValueError(f"execution_st_policy_blocked:{code}:{day}; INCOMPLETE")
        return bar

    def get_history(self, code, end_date, lookback_days):
        if code not in self.raw_codes:
            return ()
        return self.provider.get_history(code, end_date, lookback_days)


class PolicyQuantityRule(QuantityRule):
    """在已审数量校验成功后登记方向；不修改core订单或原始行情。"""
    gate_code: str
    gate_execution_day: date
    gate_market: SparseMarket
    def __init__(self, rule, code, execution_day, market):
        super().__init__(rule.minimum, rule.step, rule.maximum, rule.source_id,
                         rule.effective_from, rule.effective_through)
        object.__setattr__(self, "gate_code", code)
        object.__setattr__(self, "gate_execution_day", execution_day)
        object.__setattr__(self, "gate_market", market)

    def validate(self, side, shares, trading_date, *, available_shares=None):
        super().validate(side, shares, trading_date, available_shares=available_shares)
        requests = self.gate_market.buy_requests if side is Side.BUY else self.gate_market.sell_requests
        requests.add((self.gate_code, self.gate_execution_day))


PUBLIC_DATE_FIELDS = ("公告日期", "预案公告日", "分红实施公告日", "实施公告日", "预案预披露公告日", "股东大会公告日")
CA_DATE_ASSUMPTION = "后来库日期条件：公告日收盘后可用，下一交易日首次core反馈检查；非历史PIT认证"


def ca_information_state(item, day):
    """不推断进度/零金额无权益；无可用公开日期或坏日期仍保守检查。"""
    public, effective, invalid = [], [], []
    for field in (*PUBLIC_DATE_FIELDS, "股权登记日", "除权除息日", "派息日", "红股上市日", "实施日期", "实施日"):
        value = item.raw_row.get(field)
        if value is None or value == "":
            continue
        try:
            parsed = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            invalid.append(field)
            continue
        (public if field in PUBLIC_DATE_FIELDS else effective).append(parsed)
    if item.record_date is not None:
        effective.append(item.record_date)
    if item.event is not None:
        effective.extend(d for d in (item.event.ex_date, item.event.pay_date, item.event.listing_date) if d is not None)
    earliest = min(public) if public else None
    if invalid:
        boundary = "invalid_date_field_fail_closed"
    elif earliest is None:
        boundary = "no_publication_date_fail_closed"
    elif any(d <= day for d in effective):
        boundary = "effective_date_arrived"
    elif earliest < day:
        boundary = "publication_following_date"
    else:
        boundary = "deferred_future_publication"
    return {"inspect_now": boundary != "deferred_future_publication", "boundary": boundary,
        "earliest_public_date": None if earliest is None else str(earliest),
        "publication_fields": {k: item.raw_row.get(k) for k in PUBLIC_DATE_FIELDS},
        "effective_dates": sorted({str(d) for d in effective}), "invalid_date_fields": invalid,
        "assumption": CA_DATE_ASSUMPTION, "source_snapshot": "later_database_snapshot",
        "official_document_pin": "UNKNOWN", "historical_known_at_pin": "UNKNOWN", "implementation_pin": "UNKNOWN"}


def ca_exposure(snapshot, window):
    """仅留来源风险，绝不以事后CA资料筛选任何信号日的候选。"""
    end = window.execution_calendar[-1]
    exposure = {}
    for item in snapshot.descriptors:
        event = item.event
        dates = {item.record_date}
        if event is not None:
            dates |= {event.ex_date, event.pay_date, event.listing_date}
        dates.discard(None)
        flags = ["announcement_known_at_unknown"]
        if event is None and item.record_date is not None:
            flags.append("implementation_not_certified")
        if item.record_date is None:
            classification = "record_unknown"
        elif dates and min(dates) > end:
            classification = "future_out_of_window"
        else:
            classification = "actual_record_observer_required"
        exposure.setdefault(item.instrument_id, []).append({
            "event_id": item.event_id, "source_table": item.source_table,
            "record_date": None if item.record_date is None else item.record_date.isoformat(),
            "known_stage_dates": sorted(d.isoformat() for d in dates),
            "classification": classification, "blocking_reasons": [], "flags": flags,
            "announced_date_field": item.raw_row.get("公告日期"),
            "known_at": "UNKNOWN", "pit_verified": False,
            "date_semantics": CA_DATE_ASSUMPTION,
            "guard_boundary": "已纳入日期条件且缺登记日的首次正持仓；有效日/正登记权益不延迟"})
    return exposure


class ObservedCAContext(CorporateActionContext):
    """只读core正持仓与登记反馈；不向策略反馈未来CA资格或维护第二账本。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.checks = []
        self._deferred_seen = set()

    def _observe(self, item, quantity, boundary):
        update = self.last_update
        self.checks.append({"source_event_id": item.event_id, "code": item.instrument_id,
            "quantity": quantity, "boundary": boundary, "pit_verified": False,
            "core_event_id": None if update is None else update.event_id,
            "date": None if update is None else update.trading_date,
            "record_date": item.record_date, "announcement_field": item.raw_row.get("公告日期"),
            "information_state": ca_information_state(item, self.reset_anchor if update is None else update.trading_date)})

    def _validate_positive(self, item, quantity):
        self._observe(item, quantity, "core_positive_registered_quantity")
        if item.source_table == "right_issue":
            self._issue(item, "rights_entitlement_unresolved")
        if item.event is not None and item.event.gross_cash_per_share is None:
            self._issue(item, "cash_amount_unknown")
        if item.event is not None and item.event.share_ratio:
            self._issue(item, "share_tax_or_fractional_policy_unknown")
        super()._validate_positive(item, quantity)

    def on_update(self, update):
        # 原observer先原样记录真实core回调；任何中断都有完整前缀。
        super().on_update(update)
        for item in self.snapshot.descriptors:
            held = update.post_state.positions.get(item.instrument_id, 0)
            if item.record_date is None and held > 0:
                timing = ca_information_state(item, update.trading_date)
                if not timing["inspect_now"]:
                    key = item.event_id, update.trading_date
                    if key not in self._deferred_seen:
                        self._observe(item, held, "deferred_future_publication")
                        self._deferred_seen.add(key)
                    continue
                self._observe(item, held, "missing_record_first_positive_holding")
                self._issue(item, "record_date_unknown_positive_holdings")

    def account_actions_for_day(self, day):
        operations = list(super().account_actions_for_day(day))
        for item in self.snapshot.descriptors:
            if item.source_table == "right_issue" and item.record_date == day:
                # 只请求core记录实际股数，不产生配股股份、现金或实施声明。
                operations.append(RecordPosition(self._record_id(item), item.event_id, item.instrument_id, day))
        return tuple(operations)


def qualify(rows_by_day, window, market, snapshot, quantity=None):
    """逐完整排名留证；资格仅使用信号当日字段，不预读次日状态。"""
    exposure, opportunities, signals = ca_exposure(snapshot, window), [], {}
    for day, rows in sorted(rows_by_day.items()):
        ranking = build_signal_ranking("本地完整榜资格前", {
            day: [dict(r, status="ready", buy_eligible=False) for r in rows]})[day]
        if len(ranking.ranks) != len(rows):
            raise ValueError("完整榜含无效分数，拒绝静默过滤")
        signals[day] = []
        for row in rows:
            code = row["instrument_id"]
            state = market.verified_states.get((code, day))
            bar = market.get_bar(code, day)
            reasons = []
            rule = None
            execution_day = window.execution_calendar[window.execution_calendar.index(day) + 1]
            try:
                if quantity is None:
                    raise QuantityRuleError("quantity_evidence_missing")
                rule = quantity(execution_day, code)
            except (QuantityRuleError, ValueError, KeyError) as error:
                reasons.append(f"quantity_rule_unknown:{error}")
            if state is None:
                reasons.append("signal_state_missing")
            else:
                for field in ("st_known", "reference_known", "limit_known"):
                    if state.get(field) is not True:
                        reasons.append(f"signal_{field}_unknown")
                if state.get("market_state") != "trading":
                    reasons.append("signal_suspended_or_unknown")
                if state.get("is_st_sec") != "0":
                    reasons.append("signal_st_or_unknown")
            if bar is None or bar.close is None:
                reasons.append("signal_raw_missing")
            events = exposure.get(code, [])
            ca_flags = [{"flag": event["classification"], "event_id": event["event_id"]}
                        for event in events if not event["blocking_reasons"]]
            ca_flags += [{"flag": flag, "event_id": event["event_id"]}
                         for event in events for flag in event["flags"]]
            if day >= window.evaluation_end:
                reasons.append("E_close_no_entry")
            eligible = not reasons
            signals[day].append(dict(row, status="ready", buy_eligible=eligible))
            opportunities.append({"signal_date": day, "execution_date": window.execution_calendar[
                window.execution_calendar.index(day) + 1], "code": code,
                "original_score": row["exp_ret"], "original_rank": ranking.ranks[code],
                "signal_state_present": state is not None, "signal_raw_present": bar is not None,
                "signal_state": state, "historical_known_at": "UNKNOWN", "pit_verified": False,
                "assumption_used": "local_hdf_fields_apply_on_labeled_day",
                "decision_buy_eligible": eligible, "rejection_reasons": reasons,
                "ca_events": events, "ca_flags": ca_flags})
            opportunities[-1]["quantity_rule_source_nullable"] = None if rule is None else rule.source_id
            opportunities[-1]["quantity_rule_effective_dates"] = None if rule is None else [
                str(rule.effective_from), str(rule.effective_through)]
    return signals, opportunities


def historical_fee(day, code):
    if not code.endswith((".SZ", ".SH")):
        raise ValueError("fee_market_unknown：不冒用沪深费率")
    market = "SZSE_A" if code.endswith(".SZ") else "SSE_A"
    return resolve_historical_costs(execution_date=day, market=market, commission=CostConfig())


class LazyFees:
    """按真实请求解析费用，未知市场不得因全榜存在而被伪填费率。"""
    def __init__(self):
        self.rows = []

    def __getitem__(self, key):
        day, code = key
        fee = historical_fee(day, code)
        self.rows.append({"date": str(day), "code": code, "cost_config": fee.model_dump(mode="json")})
        return fee


class RestrictedPrepared:
    """复用既审 prepared 接口；不关闭任何原有未知来源关卡。"""
    closed_gates = ()

    def __init__(self, window, config, signal_path, signals, market, preparation_sha):
        self.window, self.config, self.path = window, config, signal_path
        self.signal_rows, self.signal_sha256 = signals, sha(signal_path)
        self.rankings = build_signal_ranking(config.source_id, signals)
        universe = {r["instrument_id"] for rows in signals.values() for r in rows}
        covered = universe & market.raw_codes
        self.coverage = _market_coverage(market, sorted(covered), window.execution_calendar)
        absent_count = (len(universe) - len(covered)) * len(window.execution_calendar)
        self.coverage["expected_count"] += absent_count
        self.coverage["missing_bar_count"] += absent_count
        self.coverage["unknown_count"] += absent_count
        self.coverage["rows_scope"] = "所有有raw代码逐日；其余缺口计数并在完整机会中逐行保留"
        self.fee_table = LazyFees()
        self.fee_rows = self.fee_table.rows
        self.fee_source = {"kind": "lazy_actual_date_code_requests", "source": "historical_costs.py"}
        self.sources_sha256 = preparation_sha

    def validate(self, window, config, signal_path):
        if window != self.window or config != self.config or Path(signal_path) != self.path:
            raise ValueError("prepared窗口/配置/路径不匹配")
        sha(signal_path, self.signal_sha256)


def enrich_opportunities(rows, output):
    decisions = {d["signal_date"]: d for d in jsonlines(output / "core/strategy_decisions.jsonl")}
    daily = {d["date"]: d for d in jsonlines(output / "core/daily_registry.jsonl")}
    updates = jsonlines(output / "core/execution_updates.jsonl")
    for row in rows:
        day, code = str(row["signal_date"]), row["code"]
        decision = decisions.get(day, {})
        orders = [o for o in decision.get("orders", []) if o["instrument_id"] == code]
        row["order_ids"] = [o["order_id"] for o in orders]
        events = [u for u in updates if u.get("order_id") in row["order_ids"]]
        row["fill_ids"] = [u["fill_id"] for u in events if u.get("fill_id")]
        row["core_events"] = events
        row["strategy_rejections"] = [r for r in decision.get("rejections", []) if code in r]
        registry = daily.get(day, {}).get("registry", {})
        row["active_slots"] = registry.get("active_slots")
        row["unused_budget"] = registry.get("available_cash")
        core_state = daily.get(day, {}).get("core_state", {})
        row["actual_positions"] = sum(v > 0 for v in core_state.get("positions", {}).values())
        row["execution_rejection_reasons"] = []
        state = row["execution_state"]
        if state is None:
            row["execution_rejection_reasons"].append("execution_state_missing")
        else:
            for field in ("st_known", "reference_known", "limit_known"):
                if state.get(field) is not True:
                    row["execution_rejection_reasons"].append(f"execution_{field}_unknown")
            if state.get("market_state") != "trading":
                row["execution_rejection_reasons"].append("execution_suspended_or_unknown")
            if state.get("is_st_sec") != "0":
                row["execution_rejection_reasons"].append("execution_st_or_unknown")
        if not row["execution_raw_present"]:
            row["execution_rejection_reasons"].append("execution_raw_missing")
        if row["original_rank"] > 5:
            row["no_new_buy_reason"] = "policy_rank_outside5"
        elif not row["decision_buy_eligible"]:
            row["no_new_buy_reason"] = "signal_ineligible"
        elif not orders:
            row["no_new_buy_reason"] = "occupied_capacity_or_strategy_rejection_see_registry"


def run_observed_window(*, window, config, market, ca, prepared, quantity, output):
    """薄接线：既审策略/observer/exporter + 原core公开回调接口，无核心猴补。"""
    output.mkdir(exist_ok=False)
    cost = config.cost_config or CostConfig()
    registry = AllocationRegistry(initial_cash=config.initial_capital, calendar_days=list(window.execution_calendar))
    recorder = _RecordingObserver(StagedExecutionBridge(registry), registry)
    context = ObservedCAContext(ca, period_id=config.period_id, reset_anchor=window.anchor_date,
        empty_reset=True, strict_tax=False, tax_policy=config.tax_policy, delegate=recorder,
        window_end=window.execution_calendar[-1],
        calendar_sha256=_config_hash([str(d) for d in window.execution_calendar]))
    audit = {"recorder": recorder, "registry": registry, "context": context, "quantity_rule_usage": [],
             "rank_summary": _full_rank_rows(prepared.rankings), "opportunities": []}
    resolver, fee_rows, used_fees = _freeze_fees(window.execution_calendar[1:],
        sorted({r["instrument_id"] for group in prepared.signal_rows.values() for r in group}),
        cost, historical_fee, prepared)

    def quantity_for_signal(day, code):
        index = window.execution_calendar.index(day) + 1
        if index >= len(window.execution_calendar) or quantity is None:
            raise QuantityRuleError("no_next_execution_day_or_quantity_evidence")
        execution_day = window.execution_calendar[index]
        usage = {"signal_date": day, "execution_date": execution_day, "code": code}
        audit["quantity_rule_usage"].append(usage)
        try:
            rule = quantity(execution_day, code)
            usage["rule"] = _plain(rule)
            return rule
        except (ValueError, KeyError) as error:
            usage["rejected"] = str(error)
            raise QuantityRuleError(str(error)) from error

    strategy = _RecordingStrategy(registry=registry, ranking_source=MappingRankingSource(prepared.rankings),
        policy=config.policy, execution_calendar=window.execution_calendar, worst_case_cost_config=cost,
        cost_config_resolver=resolver, tick_size=config.tick_size, lot_size=config.lot_size,
        buffer_start_date=window.buffer_dates[0], quantity_rule_resolver=quantity_for_signal)
    strategy.recorder = recorder
    run_id = f"staged_{config.policy.value}_{config.source_id}_{window.signal_dates[0]}_{window.evaluation_end}"
    try:
        return _finish_observed_window(window, config, market, prepared, output, cost, registry,
            recorder, context, audit, resolver, used_fees, strategy, run_id, fee_rows)
    except Exception as error:
        audit["error"] = {"type": type(error).__name__, "reason": str(error)}
        raise
    finally:
        save(output.parent / "ca_observed_checks.json", context.checks)
        _write_final_audit(output, audit, config)


def _finish_observed_window(window, config, market, prepared, output, cost, registry,
                            recorder, context, audit, resolver, used_fees, strategy, run_id, fee_rows):
    result = run_account_backtest_from_orders(execution_calendar=list(window.execution_calendar),
        signal_dates=list(window.signal_dates), maintenance_dates=list(window.buffer_dates),
        anchor_date=window.anchor_date, evaluation_end=window.evaluation_end, strategy=strategy,
        market=market, observer=context, account_actions_provider=context.account_actions_for_day,
        execution_config=ExecutionConfig(final_liquidation="mark"),
        portfolio_config=PortfolioConfig(top_n=10, lot_size=config.lot_size), cost_config=cost,
        cost_config_resolver=resolver, run_id=run_id, model_id=f"staged_{config.policy.value}",
        initial_capital=config.initial_capital, signal_time_of_day=clock_time(15, 0))
    for snapshot in result.account_snapshots:
        positions = [p for p in snapshot.positions.values() if p.shares > 0]
        assets = snapshot.cash + snapshot.receivables_value
        if any(p.market_value is None for p in positions):
            raise ValueError("真实持仓缺估值；INCOMPLETE")
        assets += sum(p.market_value or 0 for p in positions)
        assets += sum(e.market_value for e in snapshot.unlisted_entitlements.values())
        if len(positions) > 10 or abs(assets - snapshot.nav) > 1e-6:
            raise ValueError("真实持仓上限或逐日NAV恒等式失败")
    end = next(s for s in result.account_snapshots if s.date == window.evaluation_end)
    provenance = {"run_id": run_id, "source_id": config.source_id, "main_nav_end": str(end.nav),
        "quantity_rule_status": "conditional_source_bound", "tax_policy": config.tax_policy,
        "signal_file_sha256": config.signal_file_sha256, "checkpoint_sha256": config.checkpoint_sha256,
        "buffer_nav_end": str(result.account_snapshots[-1].nav)}
    provenance["signal_content_sha256"] = _signal_content_fingerprint(prepared.signal_rows)
    effective = {"execution_config": _plain(ExecutionConfig(final_liquidation="mark")),
        "portfolio_config": _plain(PortfolioConfig(top_n=10, lot_size=config.lot_size)),
        "static_cost": _plain(cost), "fee_table": fee_rows, "core_engine_version": result.engine_version,
        "core_policy_version": result.policy_version, "core_schema_version": result.schema_version,
        "core_runner_sha256": sha(sys.modules[run_account_backtest_from_orders.__module__].__file__),
        "observer": "ObservedCAContext", "pit_verified": False}
    config_hash = _config_hash({"config": _plain(config), "effective": effective,
                                "window": _plain(window), "source_manifest": prepared.sources_sha256})
    failures = ("execution_source_known_at_unknown", "ca_implementation_and_pit_unknown",
                "conditional_rules_only", "actual_tax_unknown")
    _write_outputs(output, result, provenance, _full_rank_rows(prepared.rankings), registry,
        window, config, config_hash, config.signal_file_sha256, recorder, strategy, effective,
        prepared.coverage, used_fees, failures, "INCOMPLETE")
    return StagedWindowOutcome(config=config, window=window, result=result, provenance=provenance,
        config_hash=config_hash, signal_file_sha256=config.signal_file_sha256,
        signal_content_sha256=provenance["signal_content_sha256"], validation_failures=failures,
        mechanical_status="INCOMPLETE", production_acceptance="INCOMPLETE")


def run_restricted(*, rows, window, market, ca, output, checkpoint_sha, quantity,
                   source_id="人工mini条件研究", source_identity=None):
    """薄调度：资格→冻结 Parquet→既审策略→真实 core。"""
    verify_reviewed()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sources_before = module_sources()
    save(output / "sources_before.json", sources_before)
    signals, opportunities = qualify(rows, window, market, ca, quantity)
    signal_path = output / "full_signals.parquet"
    pq.write_table(pa.Table.from_pylist([dict(row, date=day) for day, group in signals.items()
                                       for row in group]), signal_path)
    config = StagedWindowConfig(source_id=source_id, signal_file_sha256=sha(signal_path),
        checkpoint_sha256=checkpoint_sha, initial_capital=1_000_000, policy=Policy.B1,
        period_id="2025_restricted", tax_policy="cash_dividend_20pct_stress")
    save(output / "research_assumptions.json", {"pit_verified": False,
         "历史时点": "UNKNOWN", "未来权益公告时点": "未认证；不影响候选资格，按来源日期条件核实际暴露",
         "ca_publication_assumption": CA_DATE_ASSUMPTION,
         "ca_unknown_boundary": "缺公开日期立即检查；未来公告仅延后纳入，已到有效日/实际正登记不延后",
         "ca_unknown_pins": {"official_document": "UNKNOWN", "historical_known_at": "UNKNOWN", "implementation": "UNKNOWN"},
         "ca_record_assumption": "源登记日作为条件事件日使用，不宣称当时已知或已实施",
         "cash_tax": "20%现金股息压力情景，非实际个人税", "ca": ca.evidence(),
         "quantity_fixture_only": getattr(quantity, "fixture_only", None),
         "quantity_evidence": getattr(quantity, "artifacts", {}),
         "quantity_assumptions": getattr(quantity, "evidence_metadata", {}),
         "execution_st_guard": "只拦经数量校验的新买请求；已知ST的SELL保留原known及直接绝对限价，未知ST由core拒绝",
         "quantity_official_2025_confirmed": False})
    outcome, error = None, None
    try:
        preparation_path = output / "runner_preparation.json"
        save(preparation_path, {"signal_file": str(signal_path), "signal_sha256": sha(signal_path),
            "calendar": [str(d) for d in window.execution_calendar], "ca_files": dict(ca.file_sha256),
            "ca_manifest_sha256": ca.manifest_sha256, "quantity_artifacts": getattr(quantity, "artifacts", {}),
            "market_type": type(market.provider).__qualname__, "raw_codes": sorted(market.raw_codes),
            "signal_source_identity": source_identity, "checkpoint_sha256": checkpoint_sha,
            "source_known": False, "pit_verified": False, "does_not_close_source_gates": True})
        prepared = RestrictedPrepared(window, config, signal_path, signals, market, sha(preparation_path))
        market.buy_requests.clear()
        market.sell_requests.clear()
        def execution_quantity(day, code):
            if quantity is None:
                raise QuantityRuleError("quantity_evidence_missing")
            return PolicyQuantityRule(quantity(day, code), code, day, market)
        market.execution_guard = True
        outcome = run_observed_window(window=window, config=config, market=market, ca=ca,
            quantity=execution_quantity if quantity is not None else None,
            prepared=prepared, output=output / "core")
    except Exception as exc:  # noqa: BLE001
        error = {"type": type(exc).__name__, "reason": str(exc)}
    finally:
        market.execution_guard = False
        save(output / "order_policy_guards.json", {"kind": "validated_intents_not_core_fills",
            "buy_requests": sorted(market.buy_requests), "sell_requests": sorted(market.sell_requests),
            "known_st_blocks_new_buy_only": True, "does_not_change_market_known_fields": True})
        for row in opportunities:
            day, code = row["execution_date"], row["code"]
            state = market.verified_states.get((code, day))
            row.update(execution_state_present=state is not None, execution_state=state,
                       execution_raw_present=market.get_bar(code, day) is not None)
        enrich_opportunities(opportunities, output)
        with (output / "full_opportunities.jsonl").open("w", encoding="utf-8") as stream:
            for row in opportunities:
                stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        sources_after = module_sources()
        save(output / "sources.json", sources_after)
        if any(sources_after["modules"].get(name) != identity
               for name, identity in sources_before["modules"].items()):
            raise ValueError("运行中生效源码发生变化，禁止签发机械结果")
        verify_reviewed()
    report = summarize(output, opportunities, outcome, error, market)
    save(output / "summary.json", report)
    return report


def module_sources():
    modules = {}
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if (name in ("backtest", "backtest_core") or name.startswith(("backtest.", "backtest_core."))) and filename:
            path = Path(filename).resolve()
            if (name == "backtest" or name.startswith("backtest.")) and not path.is_relative_to(REVIEWED):
                raise ValueError(f"混入非整合树模块：{path}")
            modules[name] = {"path": str(path), "sha256": sha(path)}
            if name == "backtest_core.engine.account_runner" and modules[name]["sha256"] != (
                    "aa156ec2ee7fe8ee82ea3c27a2359dc4954bd6cf3d28d00a7ece6868fc8daa00"):
                raise ValueError("指定解释器core运行器与既审SHA不一致")
    return {"reviewed_16": review_identity(), "modules": modules, "python": sys.executable,
            "sys_path": sys.path, "entry_sha256": sha(__file__)}


def jsonlines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def summarize(output, opportunities, outcome, error, market):
    updates = jsonlines(output / "core/execution_updates.jsonl")
    transitions = jsonlines(output / "core/registry_transitions.jsonl")
    trades = [u["trade"] for u in updates if u.get("trade") is not None]
    fills = [t for t in trades if t["shares"] > 0 and t["execution_price"] is not None]
    if len({t["fill_id"] for t in fills}) != len(fills):
        raise ValueError("core成交回调重复，禁止重复计算费用")
    buys = [t for t in fills if t["side"] == Side.BUY.value]
    states = [u["post_state"] for u in updates]
    peak = max((sum(v > 0 for v in s["positions"].values()) for s in states), default=0)
    slots = max((t["registry"]["active_slots"] for t in transitions), default=0)
    gaps, held_unknowns = [], []
    for update in updates:
        day = date.fromisoformat(update["trading_date"])
        for code, quantity in update["post_state"]["positions"].items():
            if quantity > 0:
                bar = market.get_bar(code, day)
                if bar is None or bar.close is None:
                    gaps.append({"code": code, "date": str(day),
                                 "reason": "held_bar_missing" if bar is None else "held_close_missing"})
            if quantity > 0:
                state = market.verified_states.get((code, day), {})
                unknown = [field for field in ("st_known", "reference_known", "limit_known") if state.get(field) is not True]
                if unknown:
                    held_unknowns.append({"code": code, "date": str(day), "unknown_fields": unknown})
    if peak > 10 or slots > 5:
        raise ValueError("真实逐事件持仓或槽上限失败")
    labels = ["CONDITIONAL_RND", "INCOMPLETE", "PIT_UNPROVEN"]
    if not buys:
        labels.append("NO_EXECUTABLE_OPPORTUNITY")
    if error:
        labels.append("ABORTED_AT_POLICY_GUARD" if "execution_st_policy_blocked" in error["reason"]
                      else "ABORTED_AT_UNKNOWN_EVENT")
    snapshots = () if outcome is None else outcome.result.account_snapshots
    holding_days = len({u["trading_date"] for u in updates
                        if any(v > 0 for v in u["post_state"]["positions"].values())})
    return {"research_class": "retrospective_validation_exploration", "labels": labels,
        "target_verdict": "NOT_EVALUABLE", "pit_verified": False,
        "actual_after_tax_target_eligible": False, "full_rows": len(opportunities),
        "top5_opportunities": sum(r["original_rank"] <= 5 for r in opportunities),
        "eligible_top5": sum(r["original_rank"] <= 5 and r["decision_buy_eligible"] for r in opportunities),
        "filled_buys": len(buys), "filled_buy_amount": sum(t["amount"] for t in buys),
        "bought_codes": sorted({t["instrument_id"] for t in buys}), "fill_count": len(fills),
        "max_positions": peak, "max_active_slots": slots, "holding_days": holding_days,
        "close_holding_days": sum(any(p.shares > 0 for p in s.positions.values()) for s in snapshots),
        "costs": sum(t["commission"] + t["stamp_tax"] + t["transfer_fee"] + t["slippage_cost"] for t in fills),
        "rejection_counts": dict(Counter(reason for r in opportunities for reason in r["rejection_reasons"])),
        "core_rejection_counts": dict(Counter(u["reason"] for u in updates if u.get("reason"))),
        "held_mark_gaps": gaps, "error": error,
        "held_execution_unknowns": held_unknowns,
        "terminal_positions": {} if not states else states[-1]["positions"],
        "terminal_locked": {} if not states else states[-1]["locked"],
        "main_return_usable": error is None and not gaps and not held_unknowns,
        "main_end_nav": None if outcome is None else outcome.provenance["main_nav_end"],
        "buffer_end_nav": None if not snapshots else snapshots[-1].nav}


def run_mini(output, *, five=False, fault=None, ca_kind=None, rotation=False):
    """人工字段与人工事件夹具，真实 core 撮合与记账；不代表2025绩效。"""
    days = tuple(date.fromisoformat(d) for d in (
        "2024-12-31", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07",
        "2025-01-08", "2025-01-09", "2025-01-10"))
    window = WindowDefinition(days[0], days[4], days)
    codes = [f"{i:06d}.SZ" for i in range(1, 21 if rotation or fault in ("held_st", "held_unknown_st") else 11)]
    if fault == "unknown_market":
        codes[0] = "430001.BJ"
    known = codes if rotation else codes[:5] if five else [codes[1], codes[5]]
    states, bars = {}, []
    for code in known:
        for day in days:
            state = {"market_state": "trading", "st_known": True, "reference_known": True,
                     "limit_known": True, "is_st_sec": "0", "is_susp_sec": "0"}
            bar = make_bar(code, day, close=10, open_=10, high=10, low=10,
                volume=1_000_000, amount=10_000_000,
                absolute_limit_up_price=11, absolute_limit_down_price=9)
            if fault == "state":
                state["limit_known"] = False
            if fault == "late_entry" and day < days[3]:
                state["limit_known"] = False
            if fault == "st":
                state["is_st_sec"] = "1"
            if fault == "execution_st" and day >= days[2]:
                state["is_st_sec"] = "1"
            if fault in ("held_st", "held_unknown_st") and day >= days[3]:
                state["is_st_sec"] = "1" if fault == "held_st" else None
                if fault == "held_unknown_st":
                    state["st_known"] = False
                    bar = replace(bar, st_state_known=False)
            if fault == "suspended":
                state["market_state"] = "suspended"
                state["is_susp_sec"] = "1"
                bar = replace(bar, is_trading=False)
            if fault == "execution_limit" and day >= days[2]:
                bar = replace(bar, open=11, high=11, low=11, close=11, limit_up=True)
            if rotation and code in codes[:5] and day >= days[3]:
                bar = replace(bar, open=9, high=9, low=9, close=9, limit_down=True)
            if fault == "held_close_gap" and day == days[3]:
                bar = replace(bar, open=None, high=None, low=None, close=None)
            if fault == "held_susp" and code == known[0] and day >= days[3]:
                state["market_state"] = "suspended"
                state["is_susp_sec"] = "1"
                bar = replace(bar, is_trading=False)
            states[code, day] = state
            if not (fault == "held_raw_gap" and day == days[3]):
                bars.append(bar)
    if fault == "execution_state":
        bars = [replace(b, limit_state_known=False) if b.trading_date >= days[2] else b for b in bars]
    raw_codes = [] if fault == "raw" else known
    market = SparseMarket(SyntheticMarketProvider(bars), raw_codes, states)
    rows = {day: [{"instrument_id": code, "exp_ret": (10 - i) / 100}
                  for i, code in enumerate(codes)] for day in window.signal_dates}
    if rotation:
        for day in window.signal_dates[1:]:
            rows[day] = [{"instrument_id": code, "exp_ret": (10 - i) / 100}
                         for i, code in enumerate(codes[5:] + codes[:5])]
    if fault in ("held_st", "held_unknown_st"):
        for day in window.signal_dates[2:]:
            moved = [code for code in codes if code != "000002.SZ"] + ["000002.SZ"]
            rows[day] = [{"instrument_id": code, "exp_ret": (20 - i) / 100} for i, code in enumerate(moved)]
    ca = mini_ca(ca_kind, days, known[0])
    quantity = DateBoardQuantity([
        {"code": code, "board": "SZSE_MAIN", "start": str(days[0]), "end": str(days[-1])} for code in known],
        [{"board": "SZSE_MAIN", "minimum": 100, "step": 100, "maximum": 1_000_000,
          "source_id": "人工夹具数量规则", "start": str(days[0]), "end": str(days[-1])}], fixture_only=True)
    return run_restricted(rows=rows, window=window, market=market, ca=ca, output=output,
                          checkpoint_sha="b" * 64, quantity=quantity)


def mini_ca(kind, days, code):
    descriptors = ()
    if kind:
        row = {"id": 1, "证券代码": code, "股权登记日": days[2].strftime("%Y%m%d"),
            "除权除息日": days[3].strftime("%Y%m%d"), "派息日": days[4].strftime("%Y%m%d"),
            "每股派息税前": 0.1, "每股送转": 0, "每股送股比例": 0,
            "每股转增比例": 0, "方案进度": 3, "公告日期": None, "红股上市日": None}
        table = "dividend"
        if kind == "rights":
            table = "right_issue"
        if kind == "future_rights":
            table, row["股权登记日"] = "right_issue", "20250203"
        if kind == "future_dividend":
            row["股权登记日"], row["除权除息日"], row["派息日"] = "20250203", "20250204", "20250205"
        if kind == "no_dates":
            row["股权登记日"], row["除权除息日"] = None, None
        if kind == "missing_ex":
            row["除权除息日"] = None
        if kind == "missing_record":
            row["股权登记日"] = None
        if kind == "same_day_ex":
            row["除权除息日"] = row["股权登记日"]
        if kind == "missing_pay":
            row["派息日"] = None
        if kind == "missing_cash":
            row["每股派息税前"] = None
        if kind == "share":
            row["每股送转"] = 0.001
        row["_row_hash"] = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                                  allow_nan=False).encode()).hexdigest()
        descriptors = (descriptor_from_row(row, table=table, file_sha256="c" * 64),)
    return CorporateActionSnapshot(descriptors, {}, "d" * 64, {"fixture_only": True})


def load_npz(path, expected_sha, config):
    """原字节身份与逐键内容分别核验；true_ret 不进入交易输入。"""
    if config.get("HORIZON") != 10:
        raise ValueError("训练配置必须明确 HORIZON=10")
    digest = sha(path, expected_sha)
    with np.load(path, allow_pickle=False) as source:
        if set(source.files) != {"dates", "codes", "exp_ret", "true_ret"}:
            raise ValueError("NPZ必须恰有四个既定键")
        arrays = {key: source[key].copy() for key in source.files}
    length = len(arrays["dates"])
    if not length or any(a.ndim != 1 or len(a) != length for a in arrays.values()):
        raise ValueError("NPZ数组必须非空一维等长")
    if arrays["dates"].dtype.kind != "M" or np.isnat(arrays["dates"]).any():
        raise ValueError("NPZ日期类型或NaT错误")
    if arrays["codes"].dtype.kind != "U":
        raise ValueError("NPZ代码必须为Unicode数组")
    for key in ("exp_ret", "true_ret"):
        if arrays[key].dtype.kind != "f" or not np.isfinite(arrays[key]).all():
            raise ValueError("NPZ分数及标签必须为有限浮点数")
    days = arrays["dates"].astype("datetime64[D]")
    if not np.array_equal(days.astype(arrays["dates"].dtype), arrays["dates"]):
        raise ValueError("信号日期含非零时分秒")
    rows, seen = {}, set()
    for day, code, score in zip(days.astype(str), arrays["codes"], arrays["exp_ret"], strict=True):
        code, day = str(code), date.fromisoformat(str(day))
        if len(code) != 9 or not code[:6].isdigit() or code[6:] not in (".SZ", ".SH", ".BJ"):
            raise ValueError("NPZ代码格式无效")
        if (day, code) in seen:
            raise ValueError("NPZ存在重复日期代码")
        seen.add((day, code))
        rows.setdefault(day, []).append({"instrument_id": code, "exp_ret": float(score)})
    return {"rows": rows, "arrays": arrays, "sha256": digest,
            "key_sha256": {key: hashlib.sha256(a.tobytes()).hexdigest() for key, a in arrays.items()}}


def verify_pair(first, second):
    for key in ("dates", "codes", "true_ret"):
        a, b = first["arrays"][key], second["arrays"][key]
        if a.dtype != b.dtype or not np.array_equal(a, b):
            raise ValueError(f"A/B逐键逐值不一致：{key}")


def check_benchmark(closes, calendar):
    if any(day not in closes or not np.isfinite(closes[day]) or closes[day] <= 0 for day in calendar):
        raise ValueError("基准缺锚点、交易日或正有限收盘价；不得填充")
    return {"anchor_close": closes[calendar[0]], "end_close": closes[calendar[-1]],
            "price_return": closes[calendar[-1]] / closes[calendar[0]] - 1,
            "return_kind": "沪深300价格指数close-to-close，不含分红再投资"}


def load_local_states(path, expected_sha, source_manifest, raw_records, calendar):
    """HDF当前字节完整性和历史时点分开；不生成SDK来源证书。"""
    sha(path, expected_sha)
    audit = {}
    for source in source_manifest:
        before, after = source["file_sha256_before"], source["file_sha256_after"]
        if before != after or source["sha_origin"] != "local_hdf":
            raise ValueError("HDF来源标识或读前后SHA不一致")
        sha(source["path"], before)
        audit[source["relative_path"]] = before
    states, evidence, seen = {}, [], set()
    for row in pq.read_table(path).to_pylist():
        if any(row.get(raw) != row[canonical] for raw, canonical in HDF_MAPPING.items()):
            raise ValueError("HDF原列与canonical映射不一致")
        key = row["code"], row["date"]
        if key in seen or row["market_code"] != key[0] or row["trade_date_str"] != key[1].strftime("%Y%m%d"):
            raise ValueError("状态键重复或身份冲突")
        seen.add(key)
        if canonical_row_hash(row) != row["row_hash"] or audit.get(row["source_file_rel"]) != row["source_sha256"]:
            raise ValueError("状态rowhash或HDF来源绑定失败")
        if row["sha_origin"] != "local_hdf" or row["history_known_at"] != "UNKNOWN":
            raise ValueError("状态来源必须明确local_hdf，历史时点UNKNOWN")
        if key[1] in calendar:
            state = derive_execution_state(row, raw_records.get(key))
            state.update({field: row[field] for field in ("is_st_sec", "is_susp_sec", "is_wd_sec", "is_xr_sec")})
            state.update({field: row[field] for field in
                ("source_file_rel", "source_sha256", "row_hash", "sha_origin", "history_known_at")})
            states[key] = state
            evidence.append({"raw": row, "derived": state, "mapping_version": "local_hdf_absolute_v1",
                             "pit_verified": False, "source_response_verified": False})
    return states, evidence


def preflight_2025(output, *, quantity_input=None, quantity_sha256=None):
    """只读核验与准备一次输入；不调用全年账户。"""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    sha(LOCAL_QA_PATH, LOCAL_QA_SHA)
    identity = pinned_json("validation_2025_bridge_delivery_20261029/DATA_IDENTITY.json")
    loaded, models = {}, {}
    main_root = Path("D:/code/cnn_full_20260905/cnn")
    for model in ("A", "B"):
        expected = identity["npz"][model]
        evaluation_path = main_root / f"logs/eval_full{model}_2025.json"
        sha(evaluation_path, expected["evaluation_report_sha256"])
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        checkpoint = main_root / evaluation["checkpoint"]
        config_path = checkpoint.parent / "config.json"
        sha(checkpoint, expected["checkpoint_sha256"])
        sha(config_path, expected["config_sha256"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        loaded[model] = load_npz(expected["path"], expected["sha256"], config)
        models[model] = {**expected, "checkpoint_path": str(checkpoint), "config": config,
            "key_sha256": loaded[model]["key_sha256"], "rows": len(loaded[model]["arrays"]["dates"]),
            "signal_original_produced_at": None, "checkpoint_link": "local_evaluation_report_claim",
            "independent_certificate": False}
    verify_pair(loaded["A"], loaded["B"])
    benchmark = identity["benchmark"]
    sha(benchmark["path"], benchmark["sha256"])
    closes = {}
    for row in pq.read_table(benchmark["path"], columns=["kline_time", "close"]).to_pylist():
        day = row["kline_time"].date()
        if ANCHOR <= day <= date(2025, 12, 19):
            if day in closes:
                raise ValueError("基准日期重复")
            closes[day] = row["close"]
    calendar = tuple(sorted(closes))
    window = WindowDefinition(ANCHOR, END, calendar)
    if window.signal_dates[0] != FIRST_SIGNAL or window.buffer_dates != tuple(date(2025, 12, d) for d in (17, 18, 19)):
        raise ValueError("2025首信号或buffer日历不符")
    if any(set(item["rows"]) != set(window.signal_dates) for item in loaded.values()):
        raise ValueError("NPZ信号日与指数完整日历不一致")
    bench = check_benchmark(closes, tuple(day for day in calendar if day <= END))
    data = TEMP / "validation_2025_local_inputs_20261029"
    prefix = "validation_2025_local_inputs_20261029/"
    state_manifest = pinned_json(prefix + "full190/candidate_manifest.json")
    sources = pinned_json(prefix + "full190/source_manifest.json")
    raw_manifest = pinned_json(prefix + "raw_ohlcv_full174_v2/candidate_manifest.json")
    raw_root = data / "raw_ohlcv_full174_v2"
    for name, digest in raw_manifest["outputs_sha256"].items():
        sha(raw_root / name, digest)
    records = RawRecordLookup(raw_root, ANCHOR, calendar[-1])
    state_path = data / "full190/candidate_state.parquet"
    states, evidence = load_local_states(state_path, state_manifest["output_sha256"][state_path.name],
        [dict(source, sha_origin="local_hdf") for source in sources], records, calendar)
    with (output / "local_state_evidence.jsonl").open("w", encoding="utf-8") as stream:
        for item in evidence:
            stream.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    ca = load_corporate_action_snapshot(data / "ca_full174", expected_manifest_sha256=
        INPUT_PINS[prefix + "ca_full174/delivery_manifest_v4.json"])
    provider = CnnRawMarketDataProvider(raw_root, signal_start=ANCHOR, signal_end=END,
        execution_end=calendar[-1], history_bars=21, verified_states=states,
        corporate_action_dates=frozenset((d.instrument_id, d.event.ex_date)
            for d in ca.descriptors if d.event is not None and d.event.ex_date is not None))
    market = SparseMarket(provider, [Path(n).stem for n in raw_manifest["outputs_sha256"]], states)
    quantity, quantity_coverage = None, []
    if quantity_input is not None:
        if quantity_sha256 is None:
            raise QuantityRuleError("quantity_evidence_missing：输入必须绑定外部预期SHA")
        quantity = load_quantity_input(quantity_input, quantity_sha256)
    for code in sorted({code for code, _ in states}):
        for day in calendar[1:]:
            try:
                if quantity is None:
                    raise QuantityRuleError("quantity_evidence_missing")
                rule = quantity(day, code)
                quantity_coverage.append({"date": day, "code": code, "source_id": rule.source_id,
                                          "status": "LOCAL_BYTES_ONLY"})
            except (ValueError, KeyError) as error:
                quantity_coverage.append({"date": day, "code": code, "status": "INCOMPLETE", "reason": str(error)})
    save(output / "quantity_coverage.json", quantity_coverage)
    report = {"status": "PREPARED_CANDIDATE_ONLY", "account_started": False,
        "identity_observed_at": datetime.now(UTC).isoformat(), "models": models,
        "local_data_independent_qa": {"path": str(LOCAL_QA_PATH), "sha256": LOCAL_QA_SHA,
            "scope": "284文件与190HDF哈希，状态22码131行/raw10码80行抽样，359CA行哈希",
            "acceptance": "PARTIAL_PASS_CONDITIONAL_ONLY", "pit_certification": False,
            "full_market_certification": False, "runner_certification": False},
        "input_manifest_sha256": INPUT_PINS, "canonical_sha256": sha(state_path),
        "anchor": str(ANCHOR), "evaluation_end": str(END), "calendar": [str(d) for d in calendar],
        "benchmark": bench, "source_file_count": len(sources), "state_rows": len(states),
        "state_codes": len({code for code, _ in states}), "raw_codes": len(market.raw_codes),
        "raw_missing_codes": raw_manifest["missing_source_codes"], "ca": ca.evidence(),
        "quantity_2025": "UNRESOLVED：未提供已核2025日期板别规则" if quantity is None else "LOCAL_BYTES_ONLY_PENDING_QA",
        "quantity_input_path": None if quantity_input is None else str(quantity_input),
        "quantity_input_sha256": quantity_sha256, "quantity_official_2025_confirmed": False,
        "quantity_assumptions": getattr(quantity, "evidence_metadata", {}),
        "pit_verified": False, "source_response_verified": False,
        "actual_after_tax_target_eligible": False, "target_verdict": "NOT_EVALUABLE"}
    save(output / "prepared_manifest.json", report)
    save(output / "sources.json", module_sources())
    verify_reviewed()
    return {"report": report, "loaded": loaded, "window": window, "market": market, "ca": ca, "quantity": quantity}


def execute_ab(prepared_manifest, expected_sha256, output):
    """仅显式调用才执行A/B；主会话须先完成冻结版独立QA。"""
    sha(prepared_manifest, expected_sha256)
    frozen = json.loads(Path(prepared_manifest).read_text(encoding="utf-8"))
    if not frozen.get("quantity_input_path") or not frozen.get("quantity_input_sha256"):
        raise ValueError("quantity_evidence_missing：未绑定显式2025条件规则输入")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    prepared = preflight_2025(output / "inputs", quantity_input=frozen["quantity_input_path"],
                               quantity_sha256=frozen["quantity_input_sha256"])
    for field in ("models", "input_manifest_sha256", "canonical_sha256", "anchor", "evaluation_end", "calendar",
                  "quantity_input_sha256", "local_data_independent_qa"):
        if frozen[field] != prepared["report"][field]:
            raise ValueError(f"prepared实际输入与冻结版本不符：{field}")
    comparison = []
    for model in ("A", "B"):
        result = run_restricted(rows=prepared["loaded"][model]["rows"], window=prepared["window"],
            market=prepared["market"], ca=prepared["ca"], output=output / model,
            checkpoint_sha=frozen["models"][model]["checkpoint_sha256"], quantity=prepared["quantity"],
            source_id=f"2025_full{model}_H10_conditional", source_identity=frozen["models"][model])
        benchmark_return = prepared["report"]["benchmark"]["price_return"]
        net = None if result["main_end_nav"] is None else float(result["main_end_nav"]) / 1_000_000 - 1
        comparison.append({"model": model, **result, "same_period_hs300_price_return": benchmark_return,
            "main_net_return": net, "main_excess_return": None if net is None else net - benchmark_return,
            "conditional_numeric_criteria_met": None if net is None or not result["main_return_usable"] or
                result["filled_buys"] == 0 else
                net >= 0 and net > benchmark_return and result["max_positions"] <= 10})
    save(output / "A_B_comparison.json", comparison)
    return comparison


def main():
    parser = argparse.ArgumentParser(description="2025受限条件研究；默认只允许mini，不启动全年")
    parser.add_argument("--mini", action="store_true", help="运行真实core人工小夹具")
    parser.add_argument("--preflight-only", action="store_true", help="核验既有A/B及本地小文件，不运行账户")
    parser.add_argument("--fetch-sz-rules", action="store_true", help="下载免费官方PDF并构造明确标记的条件主板规则")
    parser.add_argument("--recorded-404-log", type=Path, help="复用已取得的404日志，禁止重复联网")
    parser.add_argument("--execute-ab", action="store_true", help="仅独立QA后显式执行A/B；不会由mini或预检触发")
    parser.add_argument("--prepared-manifest", type=Path, help="冻结准备清单路径")
    parser.add_argument("--prepared-sha256", help="冻结准备清单原字节SHA")
    parser.add_argument("--quantity-input", type=Path, help="显式日期板别规则JSON；须同时指定SHA")
    parser.add_argument("--quantity-sha256", help="规则JSON外部预期原字节SHA")
    parser.add_argument("--output", type=Path, required=True, help="不存在的新输出路径")
    args = parser.parse_args()
    if sum((args.mini, args.preflight_only, args.fetch_sz_rules, args.execute_ab)) != 1:
        parser.error("必须且只能选择一个动作；全年运行留待独立QA")
    # 既审身份硬校验：延迟化只解除 import 期副作用，任何真实研究动作仍 fail-closed。
    review_identity()
    if args.execute_ab:
        if not args.prepared_manifest or not args.prepared_sha256:
            parser.error("A/B执行必须提供冻结准备清单路径与SHA")
        execute_ab(args.prepared_manifest, args.prepared_sha256, args.output)
        return 0
    if args.fetch_sz_rules:
        print(json.dumps(fetch_sz_rules(args.output, recorded_404_log=args.recorded_404_log), ensure_ascii=False))
        return 0
    if args.preflight_only:
        if bool(args.quantity_input) != bool(args.quantity_sha256):
            parser.error("规则输入路径和SHA必须同时提供")
        prepared = preflight_2025(args.output, quantity_input=args.quantity_input, quantity_sha256=args.quantity_sha256)
        print(json.dumps({key: prepared["report"][key] for key in
            ("status", "account_started", "state_rows", "state_codes", "raw_codes", "quantity_2025")},
            ensure_ascii=False, indent=2))
        return 0
    report = run_mini(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["filled_buys"] and report["error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
