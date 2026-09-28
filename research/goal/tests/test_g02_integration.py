"""G02 集成收口 smoke：默认 adapter 路径 CLI 端到端，全 mock/合成零触库零触网。

为什么做：G01 已切默认入口，但 committed 测试只覆盖 mock 路由与 runner
直调；本文件锁定生产 CLI（main(argv) → backtest.json + manifest.json 双落盘）
的 adapter 口径：engine=goal_adapter、无 legacy 键、manifest 七键齐全
（含 config_hash/data_fingerprint 联合键，见 runner G02 指纹决策）。
"""
import json
import os
import tempfile
import unittest
from datetime import date, timedelta

import pandas as pd

import backtest.engine as entry

_CODES = ("AAA.SZ", "BBB.SH")
_MANIFEST_KEYS = {"config_hash", "data_fingerprint", "order_entry", "strategy",
                  "run_id", "created_at", "provenance"}


def _synthetic_dual_source(tmpdir: str) -> tuple[str, str, int]:
    """2 码 × 10 日确定性上涨合成双源（沿 G01 口径，码后缀可识别板块）。"""
    days = [date(2025, 3, 3) + timedelta(days=i) for i in range(10)]
    mkt_rows, pred_rows = [], []
    for day_index, day in enumerate(days):
        for code_index, code in enumerate(_CODES):
            price = round(10.0 + day_index * 0.5 + code_index, 2)
            mkt_rows.append({"code": code, "kline_time": pd.Timestamp(day), "open": price,
                             "high": price, "low": price, "close": price,
                             "volume": 2_000_000.0, "amount": 2_000_000.0 * price,
                             "is_trading": True})
            pred_rows.append({"code": code, "kline_time": pd.Timestamp(day),
                              "score": float(code_index), "future_ret_5d": 0.01, "q_true": 1})
    mkt_path = os.path.join(tmpdir, "mkt.parquet")
    pred_path = os.path.join(tmpdir, "pred.parquet")
    pd.DataFrame(mkt_rows).to_parquet(mkt_path, index=False)
    pd.DataFrame(pred_rows).to_parquet(pred_path, index=False)
    return mkt_path, pred_path, len(days)


class TestG02AdapterCliEndToEnd(unittest.TestCase):
    def test_default_cli_writes_adapter_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mkt_path, pred_path, _ = _synthetic_dual_source(tmp)
            out = os.path.join(tmp, "out")
            entry.main(["--pred", pred_path, "--market", mkt_path, "--out", out])
            with open(os.path.join(out, "backtest.json"), encoding="utf-8") as f:
                saved = json.load(f)
            with open(os.path.join(out, "manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
        self.assertEqual(saved["engine"], "goal_adapter")
        self.assertNotIn("legacy", saved)
        self.assertGreater(saved["final_nav"], 0.0)
        self.assertEqual(manifest.keys(), _MANIFEST_KEYS)
        self.assertEqual(manifest["config_hash"], saved["config_hash"])
        self.assertEqual(manifest["data_fingerprint"], saved["data_fingerprint"])

    def test_default_cli_requires_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, pred_path, _ = _synthetic_dual_source(tmp)
            with self.assertRaises(ValueError):
                entry.main(["--pred", pred_path, "--out", os.path.join(tmp, "out")])


if __name__ == "__main__":
    unittest.main()
