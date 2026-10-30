"""分批候选运行器定向 TDD 测试（第二轮重构）。

使用真实 pyarrow Parquet 写入→load_frozen_signal_parquet→hash校验，
WindowDefinition signal/buffer 从 execution_calendar 派生。
覆盖：E 收盘与 buffer 无 BUY、E-1 单可在 E 执行、buffer SELL 身份、DAY 单次终态、
满 5 槽、账户守恒、来源篡改/缺列拒绝、输出拒覆盖/真实产物。
"""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.contracts.config import CostConfig
from backtest_core.contracts.enums import Side
from backtest_core.contracts.market import MarketBar
from backtest_core.testing.synthetic import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.ca.corporate_actions import CorporateActionProvider
from backtest.cnn_adapter.staged_allocation import Policy
from backtest.cnn_adapter.staged_candidate_runner import (
    StagedWindowConfig,
    StagedWindowOutcome,
    WindowDefinition,
    load_frozen_signal_parquet,
    run_staged_window,
)
from backtest.cnn_adapter.staged_execution_bridge import StagedExecutionBridge


def _trading_days(start: date, count: int) -> list[date]:
    result: list[date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def _write_signal_parquet(
    path: Path,
    rows_by_date: dict[date, list[dict]],
) -> str:
    """写出 mini 信号 Parquet，返回文件字节 SHA-256。"""
    records: list[dict] = []
    for day, rows in sorted(rows_by_date.items()):
        for row in rows:
            f4_row = dict(row)
            f4_row["code"] = f4_row.pop("instrument_id")
            records.append({"date": day, **f4_row})
    table = pa.Table.from_pylist(records)
    pq.write_table(table, str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MiniFixture:
    """构建 mini W1 窗口夹具，输出临时 Parquet + SyntheticMarket。"""

    def __init__(self) -> None:
        self.anchor_date = date(2021, 1, 4)
        raw = _trading_days(date(2021, 1, 5), 10)
        # signal_dates = anchor(2021-01-04) 之后到 E 的全部日
        self.evaluation_end = raw[4]  # 第5日为 E
        # 完整窗口要求 E 后恰好三个交易日。
        self.buffer_dates_list = [d for d in raw[5:8] if d.weekday() < 5][:3]
        # 完整日历：anchor + 全部日至 buffer 末
        all_d = [self.anchor_date]
        cur = self.anchor_date + timedelta(days=1)
        last_b = self.buffer_dates_list[-1] if self.buffer_dates_list else raw[4]
        while cur <= last_b:
            if cur.weekday() < 5:
                all_d.append(cur)
            cur += timedelta(days=1)
        self.execution_calendar = tuple(sorted(set(all_d)))
        self.codes = ["000001.SZ", "000002.SZ", "000003.SZ",
                      "000004.SZ", "000005.SZ"]
        # 合成行情
        bars: list[MarketBar] = []
        for code in self.codes:
            for day in self.execution_calendar:
                bars.append(make_bar(
                    code, day, close=10.0, open_=10.0, high=10.0, low=10.0,
                    volume=1_000_000, amount=10_000_000,
                    absolute_limit_up_price=100.0, absolute_limit_down_price=1.0,
                ))
        self.market = SyntheticMarketProvider(bars)
        # 信号数据
        self.signal_rows: dict[date, list[dict]] = {}
        sig_dates = [d for d in self.execution_calendar
                     if self.anchor_date < d <= self.evaluation_end]
        for day in sig_dates:
            rows = []
            for j, code in enumerate(self.codes):
                exp_ret = round(0.05 - j * 0.012, 6)
                eligible = j < 3
                rows.append({
                    "instrument_id": code, "status": "ready",
                    "exp_ret": exp_ret, "buy_eligible": eligible,
                })
            self.signal_rows[day] = rows
        self.policy = Policy.B1
        self.cost_config = CostConfig()
        self.initial_capital = 1_000_000.0
        self.tick_size = 0.01
        self.lot_size = 100
        self.source_id = "test_mini_v2"

    def write_parquet(self, tmp_dir: Path) -> tuple[Path, str]:
        """写入临时候选 Parquet，返回路径和 SHA。"""
        p = tmp_dir / "mini_signal.parquet"
        sha = _write_signal_parquet(p, self.signal_rows)
        return p, sha

    def window(self) -> WindowDefinition:
        return WindowDefinition(
            anchor_date=self.anchor_date,
            evaluation_end=self.evaluation_end,
            execution_calendar=self.execution_calendar,
        )

    def config(self, sha: str) -> StagedWindowConfig:
        return StagedWindowConfig(
            source_id=self.source_id,
            signal_file_sha256=sha,
            checkpoint_sha256="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                              "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            initial_capital=self.initial_capital,
            policy=self.policy,
            tick_size=self.tick_size,
            lot_size=self.lot_size,
            tax_policy="pretax",
            cost_config=self.cost_config,
            period_id="test_W1_mini",
        )


FIX = MiniFixture()


class TestLoadParquet(unittest.TestCase):
    """load_frozen_signal_parquet 单元测试。"""

    def test_load_valid_parquet(self) -> None:
        with TemporaryDirectory() as tmp:
            p, sha = FIX.write_parquet(Path(tmp))
            loaded, actual = load_frozen_signal_parquet(p, sha)
            self.assertEqual(actual, sha)
            self.assertEqual(len(loaded), len(FIX.signal_rows))
            for day, rows in loaded.items():
                self.assertIn(day, FIX.signal_rows)
                self.assertEqual(len(rows), len(FIX.signal_rows[day]))
                self.assertIn("instrument_id", rows[0])
                self.assertNotIn("code", rows[0])

    def test_wrong_sha_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            p, _sha = FIX.write_parquet(Path(tmp))
            bad = "0000000000000000000000000000000000000000000000000000000000000000"
            with self.assertRaises(ValueError):
                load_frozen_signal_parquet(p, bad)

    def test_hash_values_require_hex_and_nonzero(self) -> None:
        with TemporaryDirectory() as tmp:
            path, _ = FIX.write_parquet(Path(tmp))
            for value in ("g" * 64, "0" * 64, "a" * 63):
                with self.subTest(value=value[:4]), self.assertRaises(ValueError):
                    load_frozen_signal_parquet(path, value)

    def test_missing_column_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "bad.parquet"
            table = pa.Table.from_pylist([
                {"date": date(2021, 1, 5),
                 "code": "000001.SZ", "exp_ret": 0.05}
            ])
            pq.write_table(table, str(p))
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                load_frozen_signal_parquet(p, sha)

    def test_missing_file_rejected(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_frozen_signal_parquet("/nonexistent/path.parquet",
                                       "a" * 64)


class TestWindowDefinition(unittest.TestCase):
    """WindowDefinition 派生逻辑。"""

    def test_derives_signal_and_buffer(self) -> None:
        win = FIX.window()
        sig = win.signal_dates
        buf = win.buffer_dates
        # 信号日覆盖锚点之后至 E，包含 E。
        expected_sig = tuple(
            d for d in FIX.execution_calendar
            if FIX.anchor_date < d <= FIX.evaluation_end
        )
        self.assertEqual(sig, expected_sig)
        # 完整生产窗口要求 E 后恰好三个交易日。
        expected_buf = tuple(
            d for d in FIX.execution_calendar
            if d > FIX.evaluation_end
        )[:3]
        self.assertEqual(buf, expected_buf)
        self.assertEqual(len(buf), 3)

    def test_date_type_check_rejects_datetime(self) -> None:
        cal = list(FIX.execution_calendar)
        cal[0] = datetime(2021, 1, 4, 0, 0, tzinfo=UTC)  # type: ignore[assignment]
        with self.assertRaises(TypeError):
            WindowDefinition(
                anchor_date=FIX.anchor_date,
                evaluation_end=FIX.evaluation_end,
                execution_calendar=tuple(cal),
            ).date_type_check()


class TestRunWindowBasic(unittest.TestCase):
    """run_staged_window 基本路径。"""

    def setUp(self) -> None:
        self.fx = MiniFixture()
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.p, self.sha = self.fx.write_parquet(self.tmp_path)
        self.out = self.tmp_path / "results"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self) -> StagedWindowOutcome:
        return run_staged_window(
            window=self.fx.window(),
            config=self.fx.config(self.sha),
            signal_parquet_path=self.p,
            market=self.fx.market,
            output_dir=str(self.out),
        )

    def test_e_close_and_buffer_no_buy(self) -> None:
        outcome = self._run()
        for trade in outcome.result.trades:
            if trade.execution_time.date() > self.fx.evaluation_end:
                self.assertNotEqual(
                    trade.side, Side.BUY,
                    f"buffer {trade.execution_time.date()} 有买入")
            if trade.signal_time.date() == self.fx.evaluation_end:
                self.assertNotEqual(
                    trade.side, Side.BUY,
                    f"E日 {trade.signal_time.date()} 有买入")

    def test_buffer_sell_with_identity(self) -> None:
        outcome = self._run()
        buf_trades = [
            t for t in outcome.result.trades
            if t.execution_time.date() > self.fx.evaluation_end
            and t.status.name == "FILLED"
        ]
        for t in buf_trades:
            self.assertIsNotNone(t.episode_id)
            self.assertIsNotNone(t.order_id)
            self.assertIsNotNone(t.fill_id)
            self.assertEqual(t.side, Side.SELL)

    def test_max_five_slots(self) -> None:
        outcome = self._run()
        slots = outcome.provenance["active_slots_end"]
        self.assertLessEqual(int(slots), 5)

    def test_nav_conservation(self) -> None:
        outcome = self._run()
        for snap in outcome.result.account_snapshots:
            computed = snap.cash + snap.receivables_value
            for p in snap.positions.values():
                if p.market_value is not None:
                    computed += p.market_value
            for e in snap.unlisted_entitlements.values():
                computed += e.market_value
            self.assertTrue(
                isclose(snap.nav, computed, rel_tol=1e-9, abs_tol=1e-6))

    def test_output_files_written(self) -> None:
        self._run()
        for name in ("manifest.json", "daily_account.jsonl",
                     "decisions_orders_fills.jsonl", "rank_summary.json",
                     "episode_summary.json"):
            self.assertTrue((self.out / name).is_file(),
                            f"缺少输出文件: {name}")

    def test_manifest_has_required_fields(self) -> None:
        self._run()
        manifest = json.loads(
            (self.out / "manifest.json").read_text(encoding="utf-8"))
        for key in ("schema_version", "run_id", "source_id", "policy",
                    "signal_file_sha256", "config_hash",
                    "anchor_date", "evaluation_end",
                    "signal_dates", "buffer_dates",
                    "main_total_return", "main_nav_end"):
            self.assertIn(key, manifest, f"manifest 缺少 {key}")
        self.assertEqual(manifest["quantity_rule_status"], "not_accepted")

    def test_output_overwrite_rejected(self) -> None:
        os.makedirs(self.out, exist_ok=True)
        (self.out / "manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            run_staged_window(
                window=self.fx.window(),
                config=self.fx.config(self.sha),
                signal_parquet_path=self.p,
                market=self.fx.market,
                output_dir=str(self.out),
            )

    def test_caller_cannot_replace_file_identity_with_self_reported_sha(self) -> None:
        unrelated_sha = "a" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(unrelated_sha),
                signal_parquet_path=self.p, market=self.fx.market)

    def test_rank_summary_all_codes(self) -> None:
        outcome = self._run()
        rank_raw = outcome.provenance.get("rank_full", "{}")
        parsed = json.loads(rank_raw)
        self.assertGreater(len(parsed), 0)
        first_day = sorted(parsed.keys())[0]
        entries = parsed[first_day]
        # 全部 5 codes 都在排名摘要中
        self.assertEqual(len(entries), 5)

    def test_modified_file_score_rejected_even_if_hash_claim_is_unchanged(self) -> None:
        changed = pa.Table.from_pylist([
            {"date": day, "code": row["instrument_id"],
             **{k: v for k, v in row.items() if k != "instrument_id"}}
            for day, day_rows in self.fx.signal_rows.items()
            for row in day_rows
        ])
        changed = changed.set_column(
            changed.schema.get_field_index("exp_ret"), "exp_ret",
            pa.array([999.0 if i == 0 else x.as_py()
                      for i, x in enumerate(changed["exp_ret"]) ]))
        pq.write_table(changed, str(self.p))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(self.sha),
                signal_parquet_path=self.p, market=self.fx.market)

    def test_deleted_high_rank_file_row_rejected_by_original_hash(self) -> None:
        table = pq.read_table(str(self.p))
        pq.write_table(table.slice(1), str(self.p))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(self.sha),
                signal_parquet_path=self.p, market=self.fx.market)

    def test_deleted_high_rank_row_cannot_be_supplied_as_mapping(self) -> None:
        loaded, _ = load_frozen_signal_parquet(self.p, self.sha)
        loaded[self.fx.window().signal_dates[0]].pop(0)
        with self.assertRaises(TypeError):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(self.sha),
                signal_parquet_path=self.p, market=self.fx.market,
                signal_rows_by_date=loaded)  # pyright: ignore[reportCallIssue]

    def test_signal_file_dates_must_exactly_match_calendar(self) -> None:
        rows = self.fx.signal_rows
        rows.pop(self.fx.window().signal_dates[-1])
        changed_sha = _write_signal_parquet(self.p, rows)
        with self.assertRaisesRegex(ValueError, "日期与窗口不一致"):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(changed_sha),
                signal_parquet_path=self.p, market=self.fx.market)


class TestFixRegression(unittest.TestCase):
    """独立 QA 的行为反例，使用真实 core。"""

    def setUp(self) -> None:
        self.fx = MiniFixture()
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.p, self.sha = self.fx.write_parquet(self.tmp_path)
        self.out = self.tmp_path / "results"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self) -> StagedWindowOutcome:
        return run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=self.fx.market, output_dir=self.out)

    def test_empty_market_is_production_blocked(self) -> None:
        outcome = run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=SyntheticMarketProvider([]), output_dir=self.out)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["mechanical_status"], "INCOMPLETE")
        self.assertEqual(manifest["production_acceptance"], "BLOCKED")
        self.assertIn("market_data_missing", outcome.validation_failures)
        self.assertTrue(manifest["validation_failures"])

    def test_legacy_provider_requires_new_context(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "corporate_action_context"):
            run_staged_window(
                window=self.fx.window(), config=self.fx.config(self.sha),
                signal_parquet_path=self.p, market=self.fx.market,
                corporate_action_provider=CorporateActionProvider([]))

    def test_real_observer_and_order_lineage_exported(self) -> None:
        received = []
        original = StagedExecutionBridge.on_update

        def consume(bridge, update):
            received.append(update)
            original(bridge, update)

        with patch.object(StagedExecutionBridge, "on_update", consume):
            outcome = self._run()
        updates = [json.loads(x) for x in (self.out / "execution_updates.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([u.event_id for u in received], [u["event_id"] for u in updates])
        for real_update, row_update in zip(received, updates, strict=True):
            self.assertEqual(dict(real_update.post_state.positions), row_update["post_state"]["positions"])
            self.assertEqual(real_update.cash_delta, row_update["cash_delta"])
        self.assertTrue(any(any(u["post_state"]["locked"].values()) for u in updates))
        self.assertEqual([u["sequence_no"] for u in updates], list(range(1, len(updates) + 1)))
        for u in updates:
            self.assertIn("pending_cash", u["post_state"])
            self.assertIn("cash_receivables", u["post_state"])
            self.assertIn("record_positions", u["post_state"])
        orders = [json.loads(x) for x in (self.out / "order_results.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(orders), len(outcome.result.order_results))
        for row, real in zip(orders, outcome.result.order_results, strict=True):
            assert real.order.shares is not None
            self.assertEqual(row["order"]["limit_price"], real.order.limit_price)
            self.assertEqual(row["remaining_shares"], real.order.shares - real.filled_shares)
        daily = [json.loads(x) for x in (self.out / "daily_registry.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(daily), len(self.fx.execution_calendar))
        self.assertTrue(any(row["episodes"] for row in daily))
        self.assertTrue(all(row["registry"]["active_slots"] <= 5 for row in daily))
        fills = [json.loads(x) for x in (self.out / "decisions_orders_fills.jsonl").read_text(encoding="utf-8").splitlines()]
        for row, event in zip(fills, outcome.result.trades, strict=True):
            self.assertEqual(row["slippage_cost"], event.slippage_cost)
            self.assertEqual(row["participation"], event.participation)
        self.assertTrue(any(row["episodes"][0]["status"] == "closed" for row in daily if row["episodes"]))

    def test_fee_resolver_changes_identity_when_nav_changes(self) -> None:
        base = self._run()
        changed = run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=self.fx.market,
            cost_config_resolver=lambda day, code: CostConfig(commission_rate=0.01))
        self.assertNotEqual(base.provenance["main_nav_end"], changed.provenance["main_nav_end"])
        self.assertNotEqual(base.config_hash, changed.config_hash)

    def test_e_minus_one_buy_executes_at_e_and_closes_without_buffer_buy(self) -> None:
        previous = self.fx.window().signal_dates[-2]
        for day, rows in self.fx.signal_rows.items():
            for row in rows:
                row["buy_eligible"] = day == previous
        self.sha = _write_signal_parquet(self.p, self.fx.signal_rows)
        outcome = self._run()
        buys = [t for t in outcome.result.trades if t.side is Side.BUY and t.shares > 0]
        self.assertTrue(buys)
        self.assertTrue(all(t.execution_time.date() == self.fx.evaluation_end for t in buys))
        self.assertTrue(all(t.signal_time.date() == previous for t in buys))
        self.assertFalse(any(t.side is Side.BUY and t.signal_time.date() >= self.fx.evaluation_end
                             for t in outcome.result.trades))
        sells = [t for t in outcome.result.trades if t.side is Side.SELL and t.shares > 0]
        self.assertTrue(sells)
        self.assertTrue(all(t.execution_time.date() in self.fx.buffer_dates_list for t in sells))

    def test_fee_table_is_frozen_once_and_stable_across_resolver_objects(self) -> None:
        calls = []

        def resolver(day: date, code: str) -> CostConfig:
            calls.append((day, code))
            return CostConfig(commission_rate=0.01)

        first = run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=self.fx.market, cost_config_resolver=resolver,
            output_dir=self.out)
        self.assertEqual(len(calls), (len(self.fx.execution_calendar) - 1) * len(self.fx.codes))
        self.assertEqual(len(calls), len(set(calls)))
        second = run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=self.fx.market,
            cost_config_resolver=lambda day, code: CostConfig(commission_rate=0.01))
        self.assertEqual(first.config_hash, second.config_hash)
        self.assertEqual(first.result.account_snapshots, second.result.account_snapshots)
        usage = [json.loads(x) for x in (self.out / "actual_fee_usage.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(usage)
        self.assertTrue(all(row["cost_config"]["commission_rate"] == 0.01 for row in usage))

    def test_missing_period_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "period_id"):
            run_staged_window(
                window=self.fx.window(), config=replace(self.fx.config(self.sha), period_id=None),
                signal_parquet_path=self.p, market=self.fx.market,
                corporate_action_provider=CorporateActionProvider([]))

    def test_strict_share_tax_rejected(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "require_known_share_tax"):
            run_staged_window(
                window=self.fx.window(), config=replace(self.fx.config(self.sha), require_known_share_tax=True),
                signal_parquet_path=self.p, market=self.fx.market)

    def test_zero_trades_with_covered_market_is_incomplete_not_missing_market(self) -> None:
        for rows in self.fx.signal_rows.values():
            for row in rows:
                row["buy_eligible"] = False
        self.sha = _write_signal_parquet(self.p, self.fx.signal_rows)
        states = {(code, day): {"market_state": "trading", "st_known": True,
                               "reference_known": True, "limit_known": True}
                  for code in self.fx.codes for day in self.fx.execution_calendar}
        with patch.object(self.fx.market, "verified_states", states, create=True):
            outcome = self._run()
        self.assertFalse(outcome.result.trades)
        self.assertEqual(outcome.production_acceptance, "INCOMPLETE")
        self.assertNotIn("market_data_missing", outcome.validation_failures)
        self.assertNotIn("market_state_coverage_unknown", outcome.validation_failures)
        manifest = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["market_coverage"]["source_known"])
        self.assertIn("quantity_rules_not_accepted", outcome.validation_failures)

    def test_state_table_count_does_not_certify_window_coverage(self) -> None:
        irrelevant = {("999999.SZ", date(1999, 1, 1)): {"market_state": "trading"}}
        with patch.object(self.fx.market, "verified_states", irrelevant, create=True):
            outcome = self._run()
        self.assertIn("market_state_coverage_unknown", outcome.validation_failures)
        rows = [json.loads(x) for x in (self.out / "market_coverage.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), len(self.fx.codes) * len(self.fx.execution_calendar))
        self.assertTrue(all("verified_states" in row["unknown_fields"] for row in rows))

    def test_pre_submission_rejections_are_exported(self) -> None:
        run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=SyntheticMarketProvider([]), output_dir=self.out)
        rows = [json.loads(x) for x in (self.out / "strategy_rejections.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all("raw_close_unknown" in row["reason"] for row in rows))

    def test_incomplete_buffers_rejected(self) -> None:
        for count in (0, 1, 2):
            days = tuple(d for d in self.fx.execution_calendar if d <= self.fx.evaluation_end)
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "3"):
                WindowDefinition(self.fx.anchor_date, self.fx.evaluation_end,
                                 days + tuple(self.fx.buffer_dates_list[:count]))

    def test_partial_day_remaining_and_terminal_are_real_core_results(self) -> None:
        days = _trading_days(date(2020, 11, 2), 40) + list(self.fx.execution_calendar)
        market = SyntheticMarketProvider(
            make_bar(code, day, close=10.0, volume=100_000, amount=1_000_000,
                     absolute_limit_up_price=100.0, absolute_limit_down_price=1.0)
            for code in self.fx.codes for day in days)
        outcome = run_staged_window(
            window=self.fx.window(), config=self.fx.config(self.sha),
            signal_parquet_path=self.p, market=market, output_dir=self.out)
        rows = [json.loads(x) for x in (self.out / "order_results.jsonl").read_text(encoding="utf-8").splitlines()]
        partial = [row for row in rows if row["status"] == "partial"]
        self.assertTrue(partial)
        updates = [json.loads(x) for x in (self.out / "execution_updates.jsonl").read_text(encoding="utf-8").splitlines()]
        for row in partial:
            self.assertGreater(row["remaining_shares"], 0)
            terminals = [u for u in updates if u["phase"] == "terminal" and u["order_id"] == row["order"]["order_id"]]
            self.assertEqual(len(terminals), 1)
            self.assertEqual(terminals[0]["order_status"], "partial")
            self.assertEqual(terminals[0]["attempt_id"], row["attempt_id"])
        self.assertEqual(len(rows), len(outcome.result.order_results))


if __name__ == "__main__":
    unittest.main()
