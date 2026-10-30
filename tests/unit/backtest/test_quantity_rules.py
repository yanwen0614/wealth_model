"""历史申报数量规则测试。"""

import unittest
from datetime import date
from typing import Any, cast

from backtest_core.contracts import Side

from backtest.cnn_adapter.quantity_rules import (
    MappingQuantityRuleResolver,
    QuantityRule,
    QuantityRuleError,
)


class QuantityRuleTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2020, 1, 2)
        self.rule = QuantityRule(200, 1, 100_000, "SSE-2019-23-20",
                                 date(2019, 3, 1), date(2023, 2, 16))

    def test_science_board_limit_buy_minimum_step_and_maximum(self):
        for shares in (100, 100_001):
            with self.subTest(shares=shares), self.assertRaises(QuantityRuleError):
                self.rule.validate(Side.BUY, shares, self.day)
        for shares in (200, 300, 100_000):
            with self.subTest(shares=shares):
                self.rule.validate(Side.BUY, shares, self.day)

    def test_sell_short_residual_is_all_or_nothing(self):
        self.rule.validate(Side.SELL, 100, self.day, available_shares=100)
        with self.assertRaises(QuantityRuleError):
            self.rule.validate(Side.SELL, 100, self.day, available_shares=300)
        self.rule.validate(Side.SELL, 200, self.day, available_shares=300)

    def test_full_balance_sale_allows_odd_lots_but_partial_sale_requires_rule(self):
        main = QuantityRule(100, 100, 100_000, "main-board-rule",
                            date(2019, 1, 1), date(2023, 12, 31))
        for shares in (122, 333):
            main.validate(Side.SELL, shares, self.day, available_shares=shares)
        with self.assertRaises(QuantityRuleError):
            main.validate(Side.SELL, 100_001, self.day, available_shares=100_001)
        with self.assertRaises(QuantityRuleError):
            main.validate(Side.SELL, 122, self.day, available_shares=333)
        with self.assertRaises(QuantityRuleError):
            self.rule.validate(Side.SELL, 100, self.day, available_shares=300)

    def test_invalid_side_date_and_resolver_interval_are_rejected(self):
        with self.assertRaises(QuantityRuleError):
            self.rule.validate(cast(Any, "BUY"), 200, self.day)
        with self.assertRaises(QuantityRuleError):
            self.rule.validate(Side.BUY, 200, cast(Any, "2020-01-02"))
        with self.assertRaises(QuantityRuleError):
            MappingQuantityRuleResolver({
                "688": (date(2020, 1, 1), date(2023, 2, 16), self.rule),
            })

    def test_source_date_and_parameters_must_be_explicit_and_valid(self):
        with self.assertRaises(QuantityRuleError):
            QuantityRule(200, 1, 100_000, "unknown", date(2019, 3, 1), date(2023, 1, 1))
        with self.assertRaises(QuantityRuleError):
            self.rule.validate(Side.BUY, 200, date(2024, 1, 1))
        with self.assertRaises(QuantityRuleError):
            QuantityRule(200, 0, 100_000, "source", date(2019, 1, 1), date(2020, 1, 1))

    def test_unknown_code_or_date_does_not_guess(self):
        resolve = MappingQuantityRuleResolver({"688": (date(2019, 3, 1), date(2023, 2, 16), self.rule)})
        self.assertIs(resolve(self.day, "688001.SH"), self.rule)
        with self.assertRaises(QuantityRuleError):
            resolve(self.day, "600001.SH")
        with self.assertRaises(QuantityRuleError):
            resolve(date(2024, 1, 1), "688001.SH")
