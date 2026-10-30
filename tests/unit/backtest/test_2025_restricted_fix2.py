"""复用独立QA两个真实probe输入，验证CA不会反向筛选历史交易。"""
import json
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import run_2025_restricted as entry

OUT = entry.TEMP / "validation_2025_restricted_fix2_20261029"
PROBES = entry.TEMP / "validation_2025_restricted_independent_qa_20261029/reverify1/evidence"
DAYS = tuple(date.fromisoformat(s) for s in (
    "2024-12-31", "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07",
    "2025-01-08", "2025-01-09", "2025-01-10"))


def probe(output, kind="none", *, raw_changes=None, target=None, fault=None):
    rows = {}
    path = PROBES / "ca_late_event_probe/none/full_signals.parquet"
    for row in entry.pq.read_table(path).to_pylist():
        day = row.pop("date")
        rows.setdefault(day, []).append(row)
    codes = sorted({r["instrument_id"] for group in rows.values() for r in group})
    bars, states = [], {}
    for code in codes:
        for day in DAYS:
            bar = entry.make_bar(code, day, close=10, open_=10, high=10, low=10,
                volume=1000000, amount=10000000,
                absolute_limit_up_price=11, absolute_limit_down_price=9)
            state = {"market_state": "trading", "st_known": True, "reference_known": True,
                     "limit_known": True, "is_st_sec": "0", "is_susp_sec": "0"}
            if fault == "suspended" and code == "000001.SZ" and day >= DAYS[3]:
                state.update(market_state="suspended", is_susp_sec="1")
                bar = replace(bar, is_trading=False)
            if fault == "unknown_st" and code == "000001.SZ" and day >= DAYS[3]:
                state.update(st_known=False, is_st_sec=None)
                bar = replace(bar, st_state_known=False)
            if fault == "missing_close" and code == "000001.SZ" and day >= DAYS[3]:
                bar = replace(bar, open=None, high=None, low=None, close=None)
            bars.append(bar)
            states[code, day] = state
    snapshot = entry.mini_ca(None, DAYS, "000001.SZ")
    if kind != "none":
        relative = ("ca_missing_record_future_probe/actual_core" if kind == "missing_record_future"
                    else f"ca_late_event_probe/{kind}")
        evidence = json.loads((PROBES / relative / "research_assumptions.json").read_text(encoding="utf-8"))
        item = evidence["ca"]["coverage"][0]
        raw = dict(item["raw_row"])
        raw.pop("_row_hash")
        raw.update(raw_changes or {})
        if target is not None:
            raw["证券代码"] = target
        raw["_row_hash"] = entry.hashlib.sha256(json.dumps(
            raw, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        descriptor = entry.descriptor_from_row(raw, table=item["source_table"], file_sha256=item["file_sha256"])
        snapshot = entry.CorporateActionSnapshot((descriptor,), {}, "d" * 64, {"fixture_only": True})
    quantity = entry.DateBoardQuantity([
        {"code": code, "board": "SZSE_MAIN", "start": str(DAYS[0]), "end": str(DAYS[-1])} for code in codes],
        [{"board": "SZSE_MAIN", "start": str(DAYS[0]), "end": str(DAYS[-1]),
          "minimum": 100, "step": 100, "maximum": 1000000, "source_id": "QA探针合成规则"}], fixture_only=True)
    market = entry.SparseMarket(entry.SyntheticMarketProvider(bars), codes, states)
    return entry.run_restricted(rows=rows, window=entry.WindowDefinition(DAYS[0], DAYS[4], DAYS),
        market=market, ca=snapshot, output=output, checkpoint_sha="b" * 64, quantity=quantity)


def fills(output, code="000001.SZ"):
    return [u["trade"] for u in entry.jsonlines(output / "core/execution_updates.jsonl")
            if u.get("fill_id") and u["trade"]["instrument_id"] == code]


class Fix2Tests(unittest.TestCase):
    def test_QA_late_event_exact_input_does_not_change_early_trades(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            root = Path(tmp)
            probe(root / "none")
            before = fills(root / "none")
            self.assertEqual([t["execution_time"][:10] for t in before], ["2025-01-03", "2025-01-07"])
            for kind in ("rights", "missing_cash"):
                report = probe(root / kind, kind)
                self.assertIsNone(report["error"])
                self.assertEqual(fills(root / kind), before)
                self.assertFalse(any(k.startswith("ca_") for k in report["rejection_counts"]))

    def test_QA_missing_record_future_requires_positive_holding_stop(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            report = probe(Path(tmp) / "缺登记未来除权", "missing_record_future")
            self.assertIsNotNone(report["error"])
            self.assertFalse(report["main_return_usable"])
            self.assertGreater(report["terminal_positions"].get("000001.SZ", 0), 0)

    def test_positive_record_stops_that_day_and_retains_unchanged_prefix(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            root = Path(tmp)
            probe(root / "none")
            for kind in ("rights", "missing_cash"):
                for announcement in (None, "20250101", "20250109"):
                    path = root / f"{kind}_{announcement}"
                    report = probe(path, kind, raw_changes={"股权登记日": "20250106", "公告日期": announcement})
                    self.assertIsNotNone(report["error"])
                    self.assertIsNone(report["main_end_nav"])
                    self.assertGreater(report["terminal_positions"].get("000001.SZ", 0), 0)
                    self.assertEqual(fills(path), fills(root / "none")[:1])
                    updates = entry.jsonlines(path / "core/execution_updates.jsonl")
                    self.assertEqual(updates[-1]["trading_date"], "2025-01-06")
                    self.assertTrue(any(v > 0 for v in updates[-1]["post_state"]["record_positions"].values()))

    def test_no_position_unknown_does_not_abort_other_codes(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            for kind in ("rights", "missing_cash", "missing_record_future"):
                path = Path(tmp) / kind
                report = probe(path, kind, target="000099.SZ")
                self.assertIsNone(report["error"])
                self.assertGreater(report["filled_buys"], 0)
                self.assertTrue(report["main_return_usable"])

    def test_sold_at_record_open_has_zero_closing_entitlement(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            report = probe(Path(tmp) / "登记日开盘已卖", "rights", raw_changes={"股权登记日": "20250107"})
            self.assertIsNone(report["error"])
            self.assertNotIn("000001.SZ", report["terminal_positions"])

    def test_suspension_unknown_st_or_missing_price_do_not_erase_entitlement(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            for fault in ("suspended", "unknown_st", "missing_close"):
                path = Path(tmp) / fault
                report = probe(path, "rights", fault=fault)
                self.assertIsNotNone(report["error"])
                self.assertFalse(report["main_return_usable"])
                self.assertGreater(report["terminal_positions"].get("000001.SZ", 0), 0)
                self.assertLessEqual(report["max_positions"], 10)

    def test_entirely_undated_event_stops_only_after_real_positive_fill(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            path = Path(tmp) / "日期全未知"
            report = probe(path, "missing_cash", raw_changes={
                "股权登记日": None, "除权除息日": None, "派息日": None, "红股上市日": None, "公告日期": None})
            self.assertGreater(len(fills(path)), 0)
            self.assertIsNotNone(report["error"])
