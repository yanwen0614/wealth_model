"""goal_adapter.common 单测（C01）：unittest.TestCase 风格，双运行器兼容."""

import unittest
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np

from goal_adapter.common import (
    default_limit_pct,
    fingerprint_mapping,
    limit_price,
    require_keys,
    signal_time_for,
)


class SignalTimeTests(unittest.TestCase):
    def test_signal_time_is_shanghai_1500_tz_aware(self):
        ts = signal_time_for(date(2024, 1, 2))
        self.assertEqual((ts.hour, ts.minute), (15, 0))
        self.assertEqual(ts.tzinfo, ZoneInfo("Asia/Shanghai"))

    def test_signal_time_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            signal_time_for(date(2024, 1, 2), mode="t0")


class RequireKeysTests(unittest.TestCase):
    def test_missing_key_raises_value_error(self):
        with self.assertRaises(ValueError):
            require_keys({"a": 1}, ["a", "b"], "test-source")

    def test_all_present_passes_silently(self):
        require_keys({"a": 1, "b": 2}, ["a", "b"], "test-source")


class FingerprintTests(unittest.TestCase):
    def test_stable_across_order_and_rewrite(self):
        arrays = {"b": np.arange(6).reshape(2, 3), "a": np.array([1.5, 2.5])}
        reordered = {"a": np.array([1.5, 2.5]), "b": np.arange(6).reshape(2, 3)}
        self.assertEqual(fingerprint_mapping(arrays), fingerprint_mapping(reordered))

    def test_content_change_changes_digest(self):
        base = {"a": np.array([1.0, 2.0])}
        mutated = {"a": np.array([1.0, 3.0])}
        self.assertNotEqual(fingerprint_mapping(base), fingerprint_mapping(mutated))


class LimitGridTests(unittest.TestCase):
    def test_amplitude_table_main_star_bse_and_st(self):
        self.assertEqual(default_limit_pct("600000.SH"), Decimal("0.10"))
        self.assertEqual(default_limit_pct("300001.SZ"), Decimal("0.20"))
        self.assertEqual(default_limit_pct("688001.SH"), Decimal("0.20"))
        self.assertEqual(default_limit_pct("430001.BJ"), Decimal("0.30"))
        self.assertEqual(default_limit_pct("600000.SH", st_codes={"600000.SH"}), Decimal("0.05"))
        # 注册制板块 ST 不降幅，避免误判涨跌停
        self.assertEqual(default_limit_pct("300001.SZ", st_codes={"300001.SZ"}), Decimal("0.20"))

    def test_limit_price_half_up_and_sz_min_tick(self):
        self.assertEqual(limit_price(10.00, 0.10, up=True), Decimal("11.00"))
        self.assertEqual(limit_price(10.00, 0.10, up=False), Decimal("9.00"))
        # 深市最小一跳：限制价与前收之差不足 1 分时取前收 ±0.01
        self.assertEqual(limit_price(0.05, 0.10, up=True, min_tick_rule=True), Decimal("0.06"))
        self.assertEqual(limit_price(0.05, 0.10, up=False, min_tick_rule=True), Decimal("0.04"))

    def test_limit_price_rejects_bad_prev_close(self):
        with self.assertRaises(ValueError):
            limit_price(0.0, 0.10, up=True)


if __name__ == "__main__":
    unittest.main()
