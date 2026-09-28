import math
import unittest

from backtest.account_engine_v6 import (
    fee_buy,
    fee_sell,
    participation_corrected,
    slip_eff,
    weight_targets,
)
from backtest.continuous_daily_executor import execute_target_weights


def market_row(open_price: float | None = 10.0, close: float | None = 10.0, volume=1_000_000.0,
               amount=10_000_000.0, is_trading=True, limit_up=100.0, limit_down=1.0):
    return {
        "open": open_price,
        "close": close,
        "volume": volume,
        "amount": amount,
        "is_trading": is_trading,
        "limit_up": limit_up,
        "limit_down": limit_down,
    }


class ContinuousDailyExecutorTests(unittest.TestCase):
    def test_projects_target_weights_in_lots_and_accounts_v6_costs(self):
        rows = {"A": market_row()}
        result = execute_target_weights(2_000.0, {}, {"A": 1.0}, rows, "2026-09-07")

        part = participation_corrected(10.0, 100, 1_000_000.0, 10_000_000.0, 10.0)
        slip_rate = slip_eff(part, "t1open")
        price = 10.0 * (1.0 + slip_rate)
        amount = price * 100
        fee = fee_buy(amount)
        self.assertEqual(result["holdings"], {"A": 100})
        self.assertAlmostEqual(result["cash"], 2_000.0 - amount - fee, places=2)
        self.assertAlmostEqual(result["fees"], fee, places=2)
        self.assertAlmostEqual(result["slip"], 10.0 * 100 * slip_rate, places=6)
        self.assertEqual(result["trades"][0]["side"], "BUY")
        self.assertEqual(result["trades"][0]["shares"], 100)

    def test_sells_before_buying_replacement_position(self):
        rows = {"A": market_row(open_price=20.0, close=20.0), "B": market_row(open_price=10.0, close=10.0)}
        result = execute_target_weights(
            0.0, {"A": 100}, {"B": 1.0}, rows, "2026-09-07"
        )

        self.assertEqual([trade["side"] for trade in result["trades"]], ["SELL", "BUY"])
        self.assertEqual(result["trades"][0]["code"], "A")
        self.assertEqual(result["holdings"], {"B": 100})

    def test_insufficient_cash_skips_unaffordable_candidate_and_fills_next(self):
        rows = {
            "EXPENSIVE": market_row(open_price=30.0, close=30.0),
            "CHEAP": market_row(open_price=10.0, close=10.0),
        }
        result = execute_target_weights(
            2_500.0, {}, {"EXPENSIVE": 0.5, "CHEAP": 0.5}, rows, "2026-09-07"
        )

        self.assertEqual(result["holdings"], {"CHEAP": 100})
        self.assertNotIn("EXPENSIVE", result["holdings"])
        self.assertGreaterEqual(result["cash"], 0.0)

    def test_skips_nontrading_missing_price_and_limit_up_buys(self):
        rows = {
            "HALT": market_row(is_trading=False),
            "MISSING": market_row(open_price=None),
            "LIMIT": market_row(open_price=10.0, limit_up=10.0),
        }
        result = execute_target_weights(
            10_000.0,
            {},
            {"HALT": 1 / 3, "MISSING": 1 / 3, "LIMIT": 1 / 3},
            rows,
            "2026-09-07",
        )

        self.assertEqual(result["holdings"], {})
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["fees"], 0.0)
        self.assertEqual(result["slip"], 0.0)

    def test_applies_v6_limit_up_buffer_to_buy(self):
        rows = {"A": market_row(open_price=9.999, close=10.0, limit_up=10.0)}

        result = execute_target_weights(
            10_000.0, {}, {"A": 1.0}, rows, "2026-09-07"
        )

        self.assertEqual(result["trades"], [])
        self.assertEqual(result["holdings"], {})
        self.assertEqual(result["cash"], 10_000.0)

    def test_sells_tradable_holding_when_close_is_missing(self):
        rows = {"A": market_row(open_price=12.0, close=None)}

        result = execute_target_weights(
            0.0, {"A": 100}, {}, rows, "2026-09-07"
        )

        self.assertEqual(result["holdings"], {})
        self.assertEqual(result["trades"][0]["side"], "SELL")

    def test_keeps_holding_when_market_row_is_not_trading(self):
        rows = {"A": market_row(open_price=12.0, close=12.0, is_trading=False)}

        result = execute_target_weights(
            0.0, {"A": 100}, {}, rows, "2026-09-07"
        )

        self.assertEqual(result["holdings"], {"A": 100})
        self.assertEqual(result["trades"], [])

    def test_sell_execution_price_uses_open_not_close(self):
        rows = {"A": market_row(open_price=12.0, close=20.0)}

        result = execute_target_weights(
            0.0, {"A": 100}, {}, rows, "2026-09-07"
        )

        part = participation_corrected(12.0, 100, 1_000_000.0, 10_000_000.0, 20.0)
        slip_rate = slip_eff(part, "t1open")
        amount = 12.0 * (1.0 - slip_rate) * 100
        self.assertAlmostEqual(result["trades"][0]["amount"], amount, places=6)

    def test_skips_non_positive_open_price(self):
        rows = {"A": market_row(open_price=0.0, close=10.0)}

        result = execute_target_weights(
            10_000.0, {}, {"A": 1.0}, rows, "2026-09-07"
        )

        self.assertEqual(result["trades"], [])
        self.assertEqual(result["cash"], 10_000.0)

    def test_rejects_fractional_holding_shares_instead_of_truncating(self):
        rows = {"A": market_row()}

        with self.assertRaises(ValueError):
            execute_target_weights(0.0, {"A": 100.5}, {}, rows, "2026-09-07")

    def test_rejects_boolean_lot_size(self):
        with self.assertRaises(ValueError):
            execute_target_weights(1_000.0, {}, {}, {}, "2026-09-07", lot_size=True)

    def test_sell_uses_v6_fee_and_slippage_and_leaves_no_fractional_lot(self):
        rows = {"A": market_row(open_price=12.0, close=12.0)}
        result = execute_target_weights(
            0.0, {"A": 200}, {}, rows, "2026-09-07", lot_size=100
        )

        part = participation_corrected(12.0, 200, 1_000_000.0, 10_000_000.0, 12.0)
        slip_rate = slip_eff(part, "t1open")
        amount = 12.0 * (1.0 - slip_rate) * 200
        fee = fee_sell(amount)
        self.assertEqual(result["holdings"], {})
        self.assertAlmostEqual(result["cash"], amount - fee, places=2)
        self.assertAlmostEqual(result["fees"], fee, places=2)
        self.assertAlmostEqual(result["slip"], 12.0 * 200 * slip_rate, places=6)


    def test_weight_targets_quadratic_nan_nonpositive_fallback(self):
        # 锁定 weight_targets 行为（PLR0124 修前锁定）：NaN/非正得分贡献为 0，
        # 全非正退化为 linear，加总恒等于 cash_total。
        self.assertEqual(weight_targets([], 300.0, "quadratic"), [])
        self.assertEqual(weight_targets([1.0, 2.0], 300.0, "equal"), [150.0, 150.0])
        self.assertEqual(weight_targets([9.0, 1.0], 300.0, "linear"), [200.0, 100.0])
        got = weight_targets([3.0, 1.0], 300.0, "quadratic")
        self.assertAlmostEqual(got[0], 300.0 * 9.5 / 11.0, places=9)
        self.assertAlmostEqual(got[1], 300.0 * 1.5 / 11.0, places=9)
        got = weight_targets([float("nan"), -1.0, 0.0], 300.0, "quadratic")
        self.assertEqual(got, [150.0, 100.0, 50.0])
        self.assertTrue(all(not math.isnan(v) for v in got))
        self.assertAlmostEqual(sum(got), 300.0, places=9)


if __name__ == "__main__":
    unittest.main()
