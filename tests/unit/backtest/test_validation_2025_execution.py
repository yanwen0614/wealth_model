"""条件历史探索run-prepared入口的真实core微型固定夹具。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from backtest_core.testing import SyntheticMarketProvider, make_bar

from backtest.cnn_adapter.corporate_action_snapshot_loader import CorporateActionSnapshot
from backtest.cnn_adapter.quantity_rules import MappingQuantityRuleResolver, QuantityRule
from backtest.cnn_adapter.staged_allocation import Policy
from backtest.cnn_adapter.staged_candidate_runner import WindowDefinition
from backtest.cnn_adapter.validation_2025_bridge import (
    convert_npz_to_frozen_parquet,
    derive_buy_eligibility,
    load_npz_signal,
)
from backtest.cnn_adapter.validation_2025_execution import (
    FROZEN_PROTOCOL,
    _load_local_raw_manifest,
    run_ab_core,
    run_prepared_accounts,
)
from scripts.run_2025_ab_execution import EVALUATION_END


class RunPreparedCoreTests(unittest.TestCase):
    def test_local_raw_manifest_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "000001.SZ.h5"
            source.write_bytes(b"original")
            manifest = root / "raw.json"
            manifest.write_text(json.dumps({
                "schema_version": "validation_2025_local_raw_v1",
                "source_kind": "local_hdf", "universe_scope": "partial",
                "files": [{"code": "000001.SZ", "path": str(source),
                           "sha256": "0" * 64}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "实际文件SHA不匹配"):
                _load_local_raw_manifest(manifest, base_dir=root,
                                         expected_codes={"000001.SZ"})

    def test_missing_run_prepared_manifest_fields_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "runs"
            with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
                run_prepared_accounts(manifest={}, base_dir=Path(temp),
                    verified={}, bridge_payload={}, run_root=output)
            self.assertFalse(output.exists())

    @staticmethod
    def _signal_rows(source, codes):
        rows = []
        for day in (date(2025, 1, 2), date(2025, 12, 15), EVALUATION_END):
            for index, code in enumerate(codes):
                rows.append({"date": day, "code": code,
                    "exp_ret": float(len(codes) - index), "true_ret": 0.01,
                    "status": "ready",
                    "buy_eligible": day != date(2025, 1, 2)
                        and not (day == date(2025, 12, 15) and index == 0)})
        return rows

    def _assert_ab_result(self, result, run_root, before_e, evaluation_end):
        self.assertEqual(set(result["accounts"]), {"A", "B"})
        self.assertEqual(result["execution"], "COMPLETED_CONDITIONAL_HISTORICAL_EXPLORATION")
        self.assertEqual(result["identity_status"], "IDENTITY_LOCAL")
        self.assertEqual(result["pit_status"], "PIT_UNPROVEN")
        self.assertEqual(result["protocol"], FROZEN_PROTOCOL)
        for source in ("A", "B"):
            account = result["accounts"][source]
            self.assertEqual(account["status"], "COMPLETED")
            self.assertEqual(account["policy"], Policy.B1.value)
            self.assertEqual(account["tranche_budget"], 200_000)
            out = run_root / source
            self.assertTrue((out / "daily_account.jsonl").is_file())
            self.assertTrue((out / "decisions_orders_fills.jsonl").is_file())
            self.assertTrue((out / "strategy_rejections.jsonl").is_file())
            self.assertTrue((out / "actual_fee_usage.jsonl").is_file())
            self.assertTrue((out / "corporate_action_evidence.json").is_file())
            core_manifest = json.loads((out / "manifest.json").read_text())
            cost = core_manifest["effective_config"]["static_cost"]
            self.assertEqual(cost["commission_rate"], 0.0002)
            self.assertEqual(cost["min_commission"], 5)
            self.assertEqual(cost["stamp_tax_rate"], 0.0005)
            self.assertEqual(cost["transfer_fee_rate"], 0.00001)
            self.assertEqual(cost["impact_coefficient"], 1)
            self.assertEqual(cost["sigma_window"], 20)
            fills = [json.loads(line) for line in
                     (out / "decisions_orders_fills.jsonl").read_text().splitlines()]
            buys = [row for row in fills if row["side"] == "buy" and row["status"] == "filled"]
            self.assertTrue(any(row["signal_date"] == before_e.isoformat()
                                and row["execution_date"] == evaluation_end.isoformat()
                                for row in buys))
            self.assertFalse(any(row["signal_date"] == evaluation_end.isoformat()
                                 and row["side"] == "buy" for row in fills))
            self.assertFalse(any(row["execution_date"] > evaluation_end.isoformat()
                                 and row["side"] == "buy" for row in fills))
            self.assertFalse(any(row["instrument_id"] == "000006.SZ" and row["side"] == "buy"
                                 for row in fills))
            daily = [json.loads(line) for line in (out / "daily_account.jsonl").read_text().splitlines()]
            anchor_state = next(row for row in daily if row["date"] == "2024-12-31")
            self.assertAlmostEqual(anchor_state["cash"], 1_000_000)
            end_state = next(row for row in daily
                             if row["date"] == evaluation_end.isoformat())
            self.assertLess(end_state["nav"], 1_000_000)
            self.assertTrue(all(row["held_code_count"] <= 10 for row in daily))
            self.assertEqual(next(row["held_code_count"] for row in daily
                                  if row["date"] == "2025-12-19"), 0)
            for row in daily:
                assets = (row["cash"] + row["receivables_value"]
                          + sum(pos["market_value"] or 0 for pos in row["positions"]))
                self.assertAlmostEqual(assets, row["nav"], places=6)
        self.assertAlmostEqual(result["benchmark"]["return"], 0.10)
    def test_two_reset_accounts_use_common_b1_window_and_audited_real_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            anchor = date(2024, 12, 31)
            before_e = date(2025, 12, 15)
            buffer_days = tuple(date(2025, 12, day) for day in (17, 18, 19))
            calendar = (anchor, date(2025, 1, 2), before_e, EVALUATION_END, *buffer_days)
            window = WindowDefinition(anchor, EVALUATION_END, calendar)
            codes = tuple(f"00000{i}.SZ" for i in range(1, 7))
            sources, hashes, checkpoints = {}, {}, {}
            for source in ("A", "B"):
                path = root / f"{source}.parquet"
                rows = self._signal_rows(source, codes)
                pq.write_table(pa.Table.from_pylist(rows), path)
                sources[source] = path
                hashes[source] = hashlib.sha256(path.read_bytes()).hexdigest()
                checkpoints[source] = hashlib.sha256(source.encode()).hexdigest()
            bars = [make_bar(code, day, close=10., open_=10., high=10., low=10.,
                volume=1_000_000, amount=10_000_000, absolute_limit_up_price=20.,
                absolute_limit_down_price=1.) for code in codes for day in calendar]
            snapshot = CorporateActionSnapshot((), MappingProxyType({}),
                "a" * 64, MappingProxyType({"identity": "fixture"}))
            rule = QuantityRule(100, 100, 1_000_000, "mini-fixture", anchor, buffer_days[-1])
            quantity = MappingQuantityRuleResolver({code: (anchor, buffer_days[-1], rule)
                                                     for code in codes})
            result = run_ab_core(
                window=window, signal_paths=sources, signal_sha256=hashes,
                checkpoint_sha256=checkpoints,
                market_factory=lambda _name: SyntheticMarketProvider(bars),
                corporate_action_snapshot=snapshot, quantity_rule_resolver=quantity,
                benchmark_closes={anchor: 100., EVALUATION_END: 110., buffer_days[-1]: 112.},
                run_root=root / "runs", scope={"kind": "mini_fixture", "code_count": len(codes)},
            )
            self._assert_ab_result(result, root / "runs", before_e, EVALUATION_END)
            wrong_hashes = dict(hashes)
            wrong_hashes["A"] = "0" * 64
            isolated = run_ab_core(
                window=window, signal_paths=sources, signal_sha256=wrong_hashes,
                checkpoint_sha256=checkpoints,
                market_factory=lambda _name: SyntheticMarketProvider(bars),
                corporate_action_snapshot=snapshot, quantity_rule_resolver=quantity,
                benchmark_closes={anchor: 100., EVALUATION_END: 110., buffer_days[-1]: 112.},
                run_root=root / "isolated", scope={"kind": "mini_fixture"},
            )
            self.assertEqual(isolated["accounts"]["A"]["status"], "INCOMPLETE")
            self.assertEqual(isolated["accounts"]["B"]["status"], "COMPLETED")

    def test_run_prepared_uses_verified_local_artifacts_and_marks_partial_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            calendar = (date(2024, 12, 31), date(2025, 1, 2), date(2025, 12, 15),
                EVALUATION_END, date(2025, 12, 17), date(2025, 12, 18), date(2025, 12, 19))
            codes = tuple(f"00000{i}.SZ" for i in range(1, 7))
            sources, bridge_sources, artifacts = {}, {}, []
            for source in ("A", "B"):
                npz = root / f"{source}.npz"
                dates = np.asarray([day.isoformat() for day in
                    (date(2025, 1, 2), date(2025, 12, 15), EVALUATION_END)
                    for _ in codes], dtype="datetime64[us]")
                np.savez(npz, dates=dates, codes=np.asarray(codes * 3),
                    exp_ret=np.tile(np.arange(6, 0, -1, dtype=float), 3),
                    true_ret=np.full(18, 0.01))
                checkpoint, config = root / f"{source}.pth", root / f"{source}.json"
                checkpoint.write_bytes(source.encode())
                config.write_text('{"HORIZON":10}', encoding="utf-8")
                npz_sha = hashlib.sha256(npz.read_bytes()).hexdigest()
                checkpoint_sha = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
                sources[source] = {"npz": str(npz), "npz_sha256": npz_sha,
                    "checkpoint": str(checkpoint), "checkpoint_sha256": checkpoint_sha,
                    "config": str(config), "config_sha256": config_sha,
                    "produced_at": "2026-10-29T10:00:00+08:00"}
            states_path = root / "states.parquet"
            state_rows = [{"code": code, "date": day,
                "market_state": "suspended" if day == date(2025, 1, 2) else "trading",
                "st_known": True, "reference_known": True, "limit_known": True,
                "st_flag": False,
                "limit_up": day == date(2025, 12, 15) and code == codes[0],
                "limit_down": False,
                "listing_known": True, "quantity_rule_known": True,
                "corporate_action_known": True,
                "absolute_limit_up_price": 11., "absolute_limit_down_price": 9.}
                for code in codes for day in calendar]
            pq.write_table(pa.Table.from_pylist(state_rows), states_path)
            state_map = {(row["code"], row["date"]):
                {key: value for key, value in row.items() if key not in {"code", "date"}}
                for row in state_rows}
            bridge_root = root / "bridges"
            bridge_root.mkdir()
            for source in ("A", "B"):
                signal = load_npz_signal(sources[source]["npz"],
                    expected_sha256=sources[source]["npz_sha256"])
                eligibility = derive_buy_eligibility(signal, calendar, state_map)
                result = convert_npz_to_frozen_parquet(
                    sources[source]["npz"], expected_npz_sha256=sources[source]["npz_sha256"],
                    checkpoint_path=sources[source]["checkpoint"],
                    expected_checkpoint_sha256=sources[source]["checkpoint_sha256"],
                    config_path=sources[source]["config"],
                    expected_config_sha256=sources[source]["config_sha256"],
                    produced_at=sources[source]["produced_at"], eligibility=eligibility,
                    state_source_path=states_path,
                    expected_state_source_sha256=hashlib.sha256(states_path.read_bytes()).hexdigest(),
                    output_dir=bridge_root / source)
                bridge_sources[source] = {"signal_path": str(result.path),
                    "parquet_sha256": result.parquet_sha256,
                    "npz_sha256": signal.source_sha256,
                    "checkpoint_sha256": sources[source]["checkpoint_sha256"]}
            raw_root = root / "raw"
            raw_root.mkdir()
            raw_entries = []
            for code in codes[:-1]:
                path = raw_root / f"{code}.h5"
                path.write_bytes(code.encode())
                raw_entries.append({"code": code, "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "key": "bars"})
            raw_manifest = root / "raw_manifest.json"
            raw_manifest.write_text(json.dumps({"schema_version": "validation_2025_local_raw_v1",
                "source_kind": "local_hdf", "universe_scope": "candidate_panel_partial",
                "files": raw_entries}), encoding="utf-8")
            ca_root = root / "actions"
            ca_root.mkdir()
            ca_manifest = root / "ca_manifest.json"
            ca_manifest.write_text("{}", encoding="utf-8")
            quantity_path = root / "quantity.json"
            quantity_path.write_text("{}", encoding="utf-8")
            for role, path in (("raw_market_manifest", raw_manifest),
                ("verified_states", states_path), ("corporate_actions", ca_manifest),
                ("quantity_rules", quantity_path)):
                artifacts.append({"role": role, "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            verified = {"artifacts": artifacts, "execution_calendar": calendar,
                "benchmark_closes": {calendar[0]: 100., EVALUATION_END: 110., calendar[-1]: 112.}}
            manifest = {"signal_sources": sources, "run_inputs": {
                "corporate_action_root": str(ca_root),
                "raw_market_scope": "candidate_panel_partial"}}
            bridge_payload = {"schema_version": "validation_2025_ab_bridge_v1",
                "protocol": FROZEN_PROTOCOL, "sources": bridge_sources}
            rule = QuantityRule(100, 100, 1_000_000, "mini", calendar[0], calendar[-1])
            quantity = MappingQuantityRuleResolver({code: (calendar[0], calendar[-1], rule)
                                                    for code in codes})
            snapshot = CorporateActionSnapshot((), MappingProxyType({}),
                "a" * 64, MappingProxyType({"identity": "local-fixture"}))
            def read_hdf(path, key=None):
                code = Path(path).stem
                return pd.DataFrame([{"code": code, "kline_time": datetime.combine(day, time()),
                    "open": 10., "high": 10., "low": 10., "close": 10.,
                    "volume": 100_000_000, "amount": 1_000_000_000_000,
                    "is_trading": True} for day in calendar])
            with (patch("backtest.cnn_adapter.validation_2025_execution.load_corporate_action_snapshot",
                        return_value=snapshot),
                  patch("backtest.cnn_adapter.validation_2025_execution._quantity_resolver",
                        return_value=quantity),
                  patch("backtest.cnn_adapter.validation_2025_execution.pd.read_hdf",
                        side_effect=read_hdf)):
                result = run_prepared_accounts(manifest=manifest, base_dir=root,
                    verified=verified, bridge_payload=bridge_payload, run_root=root / "prepared-runs")
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["scope"]["scope_status"], "PARTIAL_LOCAL_HDF")
            self.assertEqual(result["scope"]["source_identity_status"], "IDENTITY_LOCAL")
            self.assertEqual(result["scope"]["source_origin_status"], "UNKNOWN")
            self.assertEqual(result["scope"]["missing_code_count"], 1)
            self.assertEqual(result["identity_status"], "IDENTITY_LOCAL")
            self.assertEqual(result["pit_status"], "PIT_UNPROVEN")
            self.assertEqual({result["accounts"][key]["status"] for key in ("A", "B")},
                             {"COMPLETED"}, result)
            self.assertGreater(result["accounts"]["A"]["unknown_market_code_days"], 0)
            self.assertGreater(result["scope"]["missing_code_count"], 0)


if __name__ == "__main__":
    unittest.main()
