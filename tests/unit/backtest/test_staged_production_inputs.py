"""批准整合计划的真实 core 与来源边界反例。"""

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backtest.cnn_adapter.ca.corporate_action_context import CorporateActionContext
from backtest.cnn_adapter.ca.corporate_action_snapshot_loader import CorporateActionSnapshot
from backtest.cnn_adapter.staged_candidate_runner import run_staged_window
from tests.unit.backtest.test_staged_candidate_runner import MiniFixture


class ProductionIntegrationTests(unittest.TestCase):
    def _mini_configuration(self, root):
        from datetime import datetime, time

        import pyarrow as pa
        import pyarrow.parquet as pq

        import backtest.cnn_adapter.staged_production_inputs as inputs

        fx = MiniFixture()
        def save(name, value):
            path = root / name
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            return str(path)
        def bind(config, key, path):
            config[key + "_path"] = str(path)
            config[key + "_sha256"] = inputs.file_sha256(path)
        cfg = {"schema_version": "mini", "initial_capital": 1_000_000,
               "policies": ["B1", "S1", "S2", "C70"], "strict_tax": False,
               "tax_policy": "cash_dividend_20pct_stress", "pause_intervals": []}
        cost = fx.cost_config.model_dump()
        cost.update(commission_rate_buy=.0002, commission_rate_sell=.0002,
                    stamp_tax_rate=.001, transfer_fee_rate=.00002)
        cfg["cost_config"] = cost
        signal, signal_sha = fx.write_parquet(root)
        checkpoint = root / "weights.pth"
        checkpoint.write_bytes("仅微型来源身份夹具，不加载模型".encode())
        config_path = save("model_config.json", {"fixture": True})
        verification = save("checkpoint_verification.json", {"fixture": True})
        prereg = {"窗口": {}}
        calendar = root / "calendar.csv"
        calendar.write_text("date,benchmark_close\n" + "".join(
            f"{d},100\n" for d in fx.execution_calendar), encoding="utf-8")
        bind(cfg, "calendar_csv", calendar)
        index = root / "index.parquet"
        pq.write_table(pa.Table.from_pylist([{"code": "000300.SH", "kline_time": datetime.combine(d, time()),
                                            "close": 100.} for d in fx.execution_calendar]), index)
        bind(cfg, "index", index)
        cfg["windows"] = {}
        return self._mini_configuration_rest(root, fx, cfg, bind, save, prereg,
            signal, signal_sha, checkpoint, config_path, verification)

    def _mini_configuration_rest(self, root, fx, cfg, bind, save, prereg,
                                 signal, signal_sha, checkpoint, config_path, verification):
        import backtest.cnn_adapter.staged_production_inputs as inputs

        for name in ("W1", "W2"):
            source = f"{name}_mini_F4"
            metadata = {"checkpoint_sha256": inputs.file_sha256(checkpoint),
                "config_sha256": inputs.file_sha256(config_path),
                "feature_cols": ["open", "high", "low", "close"], "normalize": "relative",
                "label_mode": "excess", "seq_len": 60, "horizon": 10,
                "decision_calendar": [str(d) for d in fx.window().signal_dates]}
            spec = {"source_id": source, "signal_path": str(signal), "signal_sha256": signal_sha,
                "anchor": str(fx.anchor_date), "evaluation_end": str(fx.evaluation_end),
                "buffer_dates": [str(d) for d in fx.window().buffer_dates]}
            bind(spec, "signal_metadata", save(f"metadata_{name}.json", metadata))
            bind(spec, "checkpoint", checkpoint)
            bind(spec, "config", config_path)
            bind(spec, "checkpoint_verification", verification)
            cfg["windows"][name] = spec
            prereg["窗口"][name] = {"anchor": spec["anchor"], "end": spec["evaluation_end"],
                "buffer": spec["buffer_dates"], "decision_days": len(fx.window().signal_dates)}
        bind(cfg, "preregistration", save("preregistration.json", prereg))
        ca = root / "task2_v2"
        ca.mkdir()
        files = {}
        for name, payload in (("dividend_range_rows.json", []), ("right_issue_range_rows.json", []),
                              ("metadata_snapshot.json", {"mode": "ro"})):
            path = save(f"task2_v2/{name}", payload)
            files[f"task2_v2/{name}"] = {"sha256": inputs.file_sha256(path)}
        cfg["ca_root"] = str(root)
        bind(cfg, "ca_manifest", save("ca_manifest.json", {"core_data": files}))
        return self._mini_market_configuration(root, fx, cfg, bind, save)

    def _mini_market_configuration(self, root, fx, cfg, bind, save):
        from datetime import datetime, time, timedelta

        import pyarrow as pa
        import pyarrow.parquet as pq

        import backtest.cnn_adapter.staged_production_inputs as inputs

        raw_root = root / "raw_source"
        raw_root.mkdir()
        cfg["raw_market_root"] = str(raw_root)
        history = [fx.anchor_date - timedelta(days=i) for i in range(30, 0, -1)]
        for code in fx.codes:
            rows = [{"code": code, "kline_time": datetime.combine(d, time()),
                     "open": 10., "high": 10., "low": 10., "close": 10.,
                     "volume": 100_000_000, "amount": 1_000_000_000_000.}
                    for d in history + list(fx.execution_calendar)]
            pq.write_table(pa.Table.from_pylist(rows), raw_root / f"{code}.parquet")
        meta = save("security_metadata.json", {"rows": [{"market_code": c,
            "listplate_name": "主板", "listdate": 20000101, "delistdate": None} for c in fx.codes]})
        artifact = save("official_rule.json", {"fixture": True})
        rule = {"minimum": 100, "step": 100, "maximum": 1000000, "source_id": "mini-main-2021",
            "supported_from": "2021-01-01", "supported_through": "2022-01-06",
            "metadata_board": "主板", "exchange_suffix": ".SZ", "codes": fx.codes}
        for key, path in (("metadata", meta), ("artifact", artifact), ("corrections", artifact)):
            bind(rule, key, path)
        cfg["quantity_sources"] = [rule]
        source = root / "sdk_source"
        source.mkdir()
        (source / "batches").mkdir()
        (source / "scope_manifest.json").write_text(json.dumps({"缓存处理": [
            {"代码": c, "输出": [{"窗口": "W1全窗", "SHA256": "a" * 64}]} for c in fx.codes]}))
        cfg["state_source_root"] = str(source)
        states = []
        for code in fx.codes:
            for day in fx.execution_calendar:
                row = {"code": code, "date": day, "market_code": code,
                    "trade_date_str": day.strftime("%Y%m%d"), "preclose": 10.,
                    "high_limited": 100., "low_limited": 1., "high_lmt_rate": .1, "low_lmt_rate": .1,
                    "is_st_sec": "0", "is_susp_sec": "0", "is_wd_sec": "0", "is_xr_sec": "0",
                    "source_file_rel": f"cached_raw/W1全窗_{code.replace('.', '_')}.parquet",
                    "source_sha256": "a" * 64, "sha_origin": "cache_manifest", "window": "W1全窗"}
                row["row_hash"] = inputs.canonical_row_hash(row)
                states.append(row)
        return self._mini_state_configuration(root, cfg, bind, save, states)

    def _mini_state_configuration(self, root, cfg, bind, save, states):
        import pyarrow as pa
        import pyarrow.parquet as pq

        state_path = root / "canonical.parquet"
        pq.write_table(pa.Table.from_pylist(states), state_path)
        bind(cfg, "state", state_path)
        bind(cfg, "state_audit", save("state_audit.json", {"规范表SHA256": cfg["state_sha256"]}))
        gap = root / "gap.parquet"
        pq.write_table(pa.table({"code": pa.array([], type=pa.string()),
                                "date": pa.array([], type=pa.string())}), gap)
        bind(cfg, "gap_index", gap)
        return save("integration_inputs.json", cfg)

    def test_prepare_only_real_small_files_then_run_prepared_uses_cache(self):
        import backtest.cnn_adapter.staged_production_inputs as inputs

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self._mini_configuration(root)
            manifest = inputs.prepare_staged_inputs(config_path, root / "prepared")
            for source in (root / "raw_source").iterdir():
                source.unlink()
            summary = inputs.run_prepared_windows(manifest, root / "runs")
            attempts = json.loads(summary.read_text())["attempts"]
            self.assertEqual(len(attempts), 8)
            self.assertTrue(all("error" not in row for row in attempts), attempts)
            for row in attempts:
                folder = Path(row["output_dir"])
                self.assertTrue((folder / "strategy_decisions.jsonl").is_file())
                self.assertTrue((folder / "quantity_rule_usage.jsonl").is_file())
                self.assertFalse(json.loads((folder / "manifest.json").read_text())[
                    "actual_after_tax_target_eligible"])

    def test_anchor_never_resolves_execution_fee(self):
        fx = MiniFixture()
        calls = []
        def resolve(day, code):
            self.assertNotEqual(day, fx.anchor_date)
            calls.append((day, code))
            return fx.cost_config
        with TemporaryDirectory() as tmp:
            path, sha = fx.write_parquet(Path(tmp))
            run_staged_window(window=fx.window(), config=fx.config(sha),
                              signal_parquet_path=path, market=fx.market,
                              cost_config_resolver=resolve)
        self.assertTrue(calls)

    def test_sdk_absolute_bounds_and_adjusted_reference_do_not_use_yesterday(self):
        from types import SimpleNamespace

        from backtest.cnn_adapter.staged_production_inputs import derive_execution_state
        row = {"high_limited": 11., "low_limited": 9., "preclose": 9.8,
               "is_susp_sec": "0", "is_st_sec": "1", "is_wd_sec": "1", "is_xr_sec": "1"}
        raw = SimpleNamespace(open=11., close=10., market_state="unknown")
        state = derive_execution_state(row, raw)
        self.assertTrue(state["reference_known"])
        self.assertTrue(state["limit_up"])
        self.assertTrue(state["st_known"])
        for field, bad in (("is_susp_sec", True), ("is_st_sec", None), ("high_limited", 0)):
            state = derive_execution_state({**row, field: bad}, raw)
            if field == "is_susp_sec":
                self.assertEqual(state["market_state"], "unknown")
            else:
                self.assertFalse(state["st_known" if field == "is_st_sec" else "limit_known"])

    def test_prepared_cross_window_and_content_forgery_rejected(self):
        from backtest.cnn_adapter.staged_candidate_runner import _signal_content_fingerprint
        from backtest.cnn_adapter.staged_production_inputs import PreparedWindow
        fx = MiniFixture()
        with TemporaryDirectory() as tmp:
            path, sha = fx.write_parquet(Path(tmp))
            p = PreparedWindow(fx.window(), fx.source_id, str(path), sha,
                fx.config(sha).checkpoint_sha256, fx.signal_rows, {}, {},
                _signal_content_fingerprint(fx.signal_rows))
            p.validate(fx.window(), fx.config(sha), path)
            with self.assertRaisesRegex(ValueError, "跨窗"):
                p.validate(fx.window(), replace(fx.config(sha), source_id="W2_forged"), path)
            fx.signal_rows[fx.window().signal_dates[0]][0]["exp_ret"] = 999
            with self.assertRaisesRegex(ValueError, "指纹"):
                p.validate(fx.window(), fx.config(sha), path)

    def test_context_failure_retains_every_received_update(self):
        fx = MiniFixture()
        snapshot = CorporateActionSnapshot((), {}, "a" * 64, {})
        original = CorporateActionContext.on_update
        def fail(ctx, update):
            original(ctx, update)
            if update.sequence_no == 3:
                raise ValueError("真实回调后的模拟阶段失败")
        with TemporaryDirectory() as tmp:
            path, sha = fx.write_parquet(Path(tmp))
            out = Path(tmp) / "failed"
            with patch.object(CorporateActionContext, "on_update", fail):
                with self.assertRaisesRegex(ValueError, "阶段失败"):
                    run_staged_window(window=fx.window(), config=fx.config(sha),
                                      signal_parquet_path=path, market=fx.market,
                                      corporate_action_snapshot=snapshot, output_dir=out)
            evidence = json.loads((out / "corporate_action_evidence.json").read_text())
            self.assertIsNotNone(evidence["last_core_update"])
            self.assertEqual(len((out / "execution_updates.jsonl").read_text().splitlines()), 3)

    def test_provider_requests_21_history_and_does_not_swallow_schema(self):
        from datetime import date

        from backtest.cnn_adapter.ca.raw_market_inputs import RawMarketWindow
        from backtest.cnn_adapter.ca.raw_market_provider import CnnRawMarketDataProvider
        day = date(2021, 1, 4)
        with patch("backtest.cnn_adapter.ca.raw_market_provider.read_raw_market_inputs") as read:
            read.return_value = RawMarketWindow("AAA", (), (), ())
            provider = CnnRawMarketDataProvider("fake", signal_start=day, signal_end=day,
                execution_end=day, history_bars=21, allow_empty_window=frozenset({"AAA"}))
            self.assertIsNone(provider.get_bar("AAA", day))
            self.assertEqual(read.call_args.kwargs["history_bars"], 21)
            self.assertTrue(read.call_args.kwargs["allow_empty_window"])
        with patch("backtest.cnn_adapter.ca.raw_market_provider.read_raw_market_inputs",
                   side_effect=ValueError("损坏 schema")):
            with self.assertRaisesRegex(ValueError, "schema"):
                provider._records.clear()
                provider.get_bar("AAA", day)

    def test_state_mapping_missing_key_stays_local_and_source_hash_required(self):
        import hashlib
        from datetime import date

        import pyarrow as pa
        import pyarrow.parquet as pq

        from backtest.cnn_adapter.staged_production_inputs import build_execution_state_mapping
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "empty.parquet"
            pq.write_table(pa.table({"code": pa.array([], type=pa.string())}), p)
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "schema"):
                build_execution_state_mapping(p, expected_sha256=sha,
                    calendar=[date(2021, 1, 4)], raw_records={}, source_audit={})

    def test_single_unknown_sdk_field_is_local_and_forged_source_is_rejected(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        import backtest.cnn_adapter.staged_production_inputs as inputs

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = inputs._json(self._mini_configuration(root))
            rows = pq.read_table(cfg["state_path"]).to_pylist()
            rows[0]["is_st_sec"] = None
            rows[0]["row_hash"] = inputs.canonical_row_hash(rows[0])
            path = root / "changed.parquet"
            pq.write_table(pa.Table.from_pylist(rows), path)
            lookup = inputs._source_lookup(cfg["state_source_root"], {})
            days = [r["date"] for r in rows]
            states, evidence = inputs.build_execution_state_mapping(path,
                expected_sha256=inputs.file_sha256(path), calendar=days, raw_records={}, source_audit=lookup)
            self.assertFalse(states[rows[0]["code"], rows[0]["date"]]["st_known"])
            self.assertTrue(states[rows[1]["code"], rows[1]["date"]]["st_known"])
            self.assertIsNone(evidence[0]["raw"]["is_st_sec"])
            rows[0]["source_sha256"] = "b" * 64
            pq.write_table(pa.Table.from_pylist(rows), path)
            with self.assertRaisesRegex(ValueError, "source_sha256"):
                inputs.build_execution_state_mapping(path, expected_sha256=inputs.file_sha256(path),
                    calendar=days, raw_records={}, source_audit=lookup)
            rows[0]["source_sha256"] = "a" * 64
            pq.write_table(pa.Table.from_pylist(rows + rows[:1]), path)
            with self.assertRaisesRegex(ValueError, "重复键"):
                inputs.build_execution_state_mapping(path, expected_sha256=inputs.file_sha256(path),
                    calendar=days, raw_records={}, source_audit=lookup)

    def test_cli_prepare_and_batch_are_callable(self):
        import backtest.cnn_adapter.staged_production_inputs as inputs
        with patch.object(inputs, "prepare_staged_inputs", return_value=Path("prepared")) as prepare:
            inputs.main(["--config", "config.json", "--prepare-dir", "cache", "--prepare-only"])
            prepare.assert_called_once_with("config.json", "cache")
        with patch.object(inputs, "run_prepared_windows", return_value=Path("summary")) as run:
            inputs.main(["--prepared-manifest", "manifest.json", "--run-root", "runs", "--run-prepared"])
            run.assert_called_once_with("manifest.json", "runs", "exploration")

    def test_unexposed_universe_gap_does_not_globally_block_or_change_ranking(self):
        fx = MiniFixture()
        for rows in fx.signal_rows.values():
            rows.append({"instrument_id": "MISSING.SZ", "status": "ready",
                         "exp_ret": -1., "buy_eligible": False})
        states = {(code, day): {"market_state": "trading", "st_known": True,
                  "reference_known": True, "limit_known": True}
                  for code in fx.codes for day in fx.execution_calendar}
        with TemporaryDirectory() as tmp, patch.object(fx.market, "verified_states", states, create=True):
            path, sha = fx.write_parquet(Path(tmp))
            outcome = run_staged_window(window=fx.window(), config=fx.config(sha),
                                       signal_parquet_path=path, market=fx.market)
        self.assertEqual(outcome.production_acceptance, "INCOMPLETE")
        self.assertNotIn("market_data_missing", outcome.validation_failures)
        self.assertNotIn("market_state_coverage_unknown", outcome.validation_failures)
        ranks = json.loads(outcome.provenance["rank_full"])
        self.assertTrue(all(len(rows) == 6 for rows in ranks.values()))

    def test_real_quantity_resolver_queries_next_execution_date(self):
        from datetime import date

        from backtest.cnn_adapter.quantity_rules import QuantityRule
        fx, calls = MiniFixture(), []
        def resolver(day, code):
            calls.append((day, code))
            return QuantityRule(100, 100, 1_000_000, "explicit-main-2021",
                                date(2021, 1, 1), date(2022, 1, 6))
        with TemporaryDirectory() as tmp:
            path, sha = fx.write_parquet(Path(tmp))
            result = run_staged_window(window=fx.window(), config=fx.config(sha),
                signal_parquet_path=path, market=fx.market, quantity_rule_resolver=resolver,
                output_dir=Path(tmp) / "out")
            usage = [json.loads(s) for s in (Path(tmp) / "out/quantity_rule_usage.jsonl").read_text().splitlines()]
            self.assertTrue(usage)
            self.assertTrue(all(r["execution_date"] > r["signal_date"] for r in usage))
            self.assertNotIn("quantity_rules_not_accepted", result.validation_failures)
        self.assertTrue(calls)

    def test_eight_real_core_attempts_reset_and_first_failure_does_not_stop_rest(self):
        import backtest.cnn_adapter.staged_candidate_runner as runner
        import backtest.cnn_adapter.staged_production_inputs as inputs
        fx = MiniFixture()
        snapshot = CorporateActionSnapshot((), {}, "a" * 64, {})
        real_core = runner.run_account_backtest_from_orders
        attempts = []
        def core(**kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise ValueError("首窗失败继续")
            return real_core(**kwargs)
        with TemporaryDirectory() as tmp:
            path, sha = fx.write_parquet(Path(tmp))
            fees = {(d, c): fx.cost_config for d in fx.execution_calendar[1:] for c in fx.codes}
            prepared = inputs.PreparedWindow(fx.window(), fx.source_id, str(path), sha,
                fx.config(sha).checkpoint_sha256, fx.signal_rows,
                runner.build_signal_ranking(fx.source_id, fx.signal_rows),
                runner._market_coverage(fx.market, fx.codes, fx.execution_calendar),
                runner._signal_content_fingerprint(fx.signal_rows), fees, [], ())
            config = {"initial_capital": 1_000_000, "tax_policy": "cash_dividend_20pct_stress",
                      "ca_root": "unused", "ca_manifest_path": "unused", "ca_manifest_sha256": "a" * 64}
            manifest = {"config": config, "artifacts": {}, "core_path": "bound",
                        "core_sha256": "a" * 64,
                        "benchmark": {str(d): 100. for d in fx.execution_calendar}}
            with patch.object(inputs, "_verify_prepared", return_value=manifest), \
                 patch.object(inputs, "_quantity_resolver", return_value=None), \
                 patch.object(inputs, "_frozen_cost", return_value=fx.cost_config), \
                 patch.object(inputs, "load_corporate_action_snapshot", return_value=snapshot), \
                 patch.object(inputs, "_load_prepared_window", return_value=(prepared, fx.market)), \
                 patch.object(runner, "run_account_backtest_from_orders", side_effect=core):
                summary_path = inputs.run_prepared_windows("unused", Path(tmp) / "runs")
            summary = json.loads(summary_path.read_text())
            self.assertEqual(len(summary["attempts"]), 8)
            self.assertIn("首窗失败", summary["attempts"][0]["error"])
            self.assertEqual(len({id(a["observer"]) for a in attempts}), 8)
            self.assertEqual(len({id(a["strategy"]) for a in attempts}), 8)
            for row in summary["attempts"][1:]:
                updates = (Path(row["output_dir"]) / "execution_updates.jsonl").read_text().splitlines()
                first = json.loads(updates[0])["post_state"]
                self.assertEqual(first["cash"], 1_000_000)
                self.assertFalse(first["positions"])
