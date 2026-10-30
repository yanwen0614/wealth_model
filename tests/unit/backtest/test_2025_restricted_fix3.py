"""原始未来公告事件与真实core反馈；日期条件不冒充历史PIT证明。"""
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

# 证据根：W1 树已退役，2025 研究证据保存在 opencode 临时目录；
# 显式注入以保持 W1 时期 ROOT.parent 语义，不改变任何校验强度。
os.environ.setdefault("CNN_2025_EVIDENCE_ROOT", str(Path(tempfile.gettempdir()) / "opencode"))

from scripts import run_2025_restricted as entry  # noqa: E402

# 既审树已于 2026-10-30 退役，run_restricted 运行时复验该树必然失败 → 显式 skip。
SKIP_RETIRED_TREE = unittest.skipIf(
    not entry.review_identity_available(),
    "原因：依赖已于 2026-10-30 退役的 corporate-action-fix-20261027 既审树",
)

OUT = entry.TEMP / "validation_2025_restricted_fix3_20261029"
CA_ROOT = entry.TEMP / "validation_2025_local_inputs_20261029/ca_full174"
_SOURCE = None
_ORIGINAL = None


def _ca_source():
    """惰性加载CA快照：import 期不读外部证据，缺失时由用例 skip 而非崩溃。"""
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = entry.load_corporate_action_snapshot(CA_ROOT, expected_manifest_sha256=
            entry.INPUT_PINS["validation_2025_local_inputs_20261029/ca_full174/delivery_manifest_v4.json"])
    return _SOURCE


def _original():
    """惰性派生原始CA行索引；import 期不读外部证据，缺失时由用例 skip 而非崩溃。"""
    global _ORIGINAL
    if _ORIGINAL is None:
        _ORIGINAL = {int(d.raw_row["id"]): d for d in _ca_source().descriptors}
    return _ORIGINAL


EARLY = tuple(date.fromisoformat(s) for s in (
    "2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08",
    "2025-01-09", "2025-01-10", "2025-01-13"))
LATER = {
    103185: tuple(date.fromisoformat(s) for s in ("2025-07-23", "2025-07-24", "2025-07-25",
        "2025-07-28", "2025-07-29", "2025-07-30", "2025-07-31", "2025-08-01")),
    55290: tuple(date.fromisoformat(s) for s in ("2025-08-27", "2025-08-28", "2025-08-29",
        "2025-09-01", "2025-09-02", "2025-09-03", "2025-09-04", "2025-09-05")),
}


def publication_probe(output, row_id=103185, *, days=EARLY, changes=None, hold=True, empty=False, include_previous=False):
    original = _original()
    descriptor = original[row_id]
    if changes:
        raw = {k: v for k, v in descriptor.raw_row.items() if k != "_row_hash"}
        raw.update(changes)
        raw["_row_hash"] = hashlib.sha256(json.dumps(raw, sort_keys=True,
            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        descriptor = entry.descriptor_from_row(raw, table="dividend", file_sha256=raw["_row_hash"])
    source = _ca_source()
    descriptors = (descriptor, original[103186 if row_id == 103185 else 55291]) if include_previous else (descriptor,)
    snapshot = entry.CorporateActionSnapshot(() if empty else descriptors, source.file_sha256,
        source.manifest_sha256, {"fixture_only": True, "source_date_variant": bool(changes),
                                "original_row_sha256": original[row_id].raw_row["_row_hash"]})
    code = descriptor.instrument_id if hold else "000001.SZ"
    codes = [code] + [f"{i:06d}.SH" for i in range(1, 10)]
    bars = [entry.make_bar(code, day, close=10, open_=10, high=10, low=10,
        volume=1000000, amount=10000000, absolute_limit_up_price=11, absolute_limit_down_price=9) for day in days]
    states = {(code, day): {"market_state": "trading", "st_known": True, "reference_known": True,
        "limit_known": True, "is_st_sec": "0", "is_susp_sec": "0"} for day in days}
    market = entry.SparseMarket(entry.SyntheticMarketProvider(bars), [code], states)
    rows = {day: [{"instrument_id": c, "exp_ret": (10 - i) / 100} for i, c in enumerate(codes)]
            for day in days[1:5]}
    quantity = entry.DateBoardQuantity([{"code": code, "board": "SZSE_MAIN",
        "start": str(days[0]), "end": str(days[-1])}], [{"board": "SZSE_MAIN", "start": str(days[0]),
        "end": str(days[-1]), "minimum": 100, "step": 100, "maximum": 1000000,
        "source_id": "公告时序mini合成规则"}], fixture_only=True)
    return entry.run_restricted(rows=rows, window=entry.WindowDefinition(days[0], days[4], days),
        market=market, ca=snapshot, output=output, checkpoint_sha="b" * 64, quantity=quantity)


class Fix3Tests(unittest.TestCase):
    @SKIP_RETIRED_TREE
    def test_two_original_rows_do_not_abort_january_six_buy(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            root = Path(tmp)
            for row_id in (103185, 55290):
                with self.subTest(row_id=row_id):
                    base = publication_probe(root / f"base_{row_id}", row_id, empty=True)
                    report = publication_probe(root / str(row_id), row_id)
                    self.assertIsNone(report["error"])
                    self.assertEqual(report["filled_buys"], base["filled_buys"])
                    updates = entry.jsonlines(root / str(row_id) / "core/execution_updates.jsonl")
                    buy = next(u for u in updates if u.get("fill_id") and u["trade"]["side"] == "buy")
                    self.assertEqual(buy["trading_date"], "2025-01-06")
                    original = json.loads((root / str(row_id) / "research_assumptions.json").read_text(encoding="utf-8"))
                    self.assertEqual(original["ca"]["coverage"][0]["raw_row"], dict(_original()[row_id].raw_row))

    @SKIP_RETIRED_TREE
    def test_original_unknown_record_stops_only_after_publication_date(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            for row_id, days in LATER.items():
                path = Path(tmp) / str(row_id)
                report = publication_probe(path, row_id, days=days)
                self.assertIsNotNone(report["error"])
                updates = entry.jsonlines(path / "core/execution_updates.jsonl")
                self.assertEqual(updates[-1]["trading_date"], str(days[3]))
                self.assertTrue(any(u.get("fill_id") and u["trading_date"] == str(days[2]) for u in updates))
                self.assertGreater(report["terminal_positions"].get(_original()[row_id].instrument_id, 0), 0)
                self.assertFalse(report["main_return_usable"])
                checks = json.loads((path / "ca_observed_checks.json").read_text(encoding="utf-8"))
                self.assertTrue(any(c["date"] == str(days[2]) and
                    c["boundary"] == "deferred_future_publication" for c in checks))
                self.assertTrue(all(c["information_state"]["historical_known_at_pin"] == "UNKNOWN" for c in checks))

    @SKIP_RETIRED_TREE
    def test_no_usable_publication_or_past_publication_stops_at_real_fill(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            for name, changes in (("无公告", {"公告日期": None, "预案公告日": None}),
                                  ("已公告", {"公告日期": 20250102}),
                                  ("坏日期", {"公告日期": "未知文本"})):
                path = Path(tmp) / name
                report = publication_probe(path, changes=changes)
                self.assertIsNotNone(report["error"])
                updates = entry.jsonlines(path / "core/execution_updates.jsonl")
                self.assertEqual(updates[-1]["trading_date"], "2025-01-06")
                self.assertGreater(report["terminal_locked"].get("000159.SZ", 0), 0)

    @SKIP_RETIRED_TREE
    def test_earliest_plan_date_not_later_announcement_or_progress_waiver(self):
        for row_id, expected in ((103186, "2025-03-28"), (55291, "2025-04-26")):
            info = entry.ca_information_state(_original()[row_id], date(2025, 5, 6))
            self.assertEqual(info["earliest_public_date"], expected)
            self.assertTrue(info["inspect_now"])
            self.assertEqual(info["historical_known_at_pin"], "UNKNOWN")
        days = tuple(date.fromisoformat(s) for s in ("2025-03-26", "2025-03-27", "2025-03-28",
            "2025-03-31", "2025-04-01", "2025-04-02", "2025-04-03", "2025-04-07"))
        with TemporaryDirectory(dir=OUT) as tmp:
            path = Path(tmp) / "原进度2零金额"
            report = publication_probe(path, 103186, days=days)
            self.assertIsNotNone(report["error"])
            self.assertEqual(entry.jsonlines(path / "core/execution_updates.jsonl")[-1]["trading_date"], "2025-03-31")

    @SKIP_RETIRED_TREE
    def test_real_effective_boundary_precedes_future_announcement(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            for name, changes in (("先除权", {"除权除息日": 20250106}),
                                  ("先登记", {"股权登记日": 20250106, "除权除息日": 20250107,
                                              "每股派息税前": None})):
                report = publication_probe(Path(tmp) / name, changes=changes)
                self.assertIsNotNone(report["error"])
                self.assertGreater(report["terminal_positions"].get("000159.SZ", 0), 0)

    @SKIP_RETIRED_TREE
    def test_unheld_previously_public_unknown_event_does_not_abort(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            report = publication_probe(Path(tmp) / "未持有", hold=False,
                changes={"公告日期": 20250102})
            self.assertIsNone(report["error"])
            self.assertGreater(report["filled_buys"], 0)

    @SKIP_RETIRED_TREE
    def test_future_row_does_not_mask_earlier_publication_of_another_row(self):
        days = tuple(date.fromisoformat(s) for s in ("2025-03-26", "2025-03-27", "2025-03-28",
            "2025-03-31", "2025-04-01", "2025-04-02", "2025-04-03", "2025-04-07"))
        with TemporaryDirectory(dir=OUT) as tmp:
            report = publication_probe(Path(tmp) / "同股更早条目", days=days, include_previous=True)
            self.assertIsNotNone(report["error"])
            self.assertIn("dividend:103186:", report["error"]["reason"])
            self.assertGreater(report["terminal_positions"].get("000159.SZ", 0), 0)
