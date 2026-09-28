"""baseline_hgb --scaler 接线契约（run_all.sh [2/5] scaler 缺口修复的锁定测试）。

[2/5] smoke 需消费 [1/5] 生成的 $SMOKE/scaler.pkl，而非缺失的
artifacts/scaler.pkl；--scaler 缺省必须仍为 DEFAULT_SCALER（全量调用方不变）。
零触库零触网：只测参数解析，不跑训练。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "models"))
sys.path.insert(0, str(ROOT / "data"))

from baseline_hgb import DEFAULT_SCALER, parse_args


class ScalerCliTests(unittest.TestCase):
    def test_scaler_defaults_to_canonical_artifact(self):
        args = parse_args(["--smoke"])
        self.assertEqual(args.scaler, str(DEFAULT_SCALER))
        self.assertTrue(args.scaler.endswith("artifacts/scaler.pkl"))

    def test_scaler_accepts_smoke_override(self):
        args = parse_args(["--smoke", "--scaler", "/tmp/goal_smoke/scaler.pkl"])
        self.assertEqual(args.scaler, "/tmp/goal_smoke/scaler.pkl")


if __name__ == "__main__":
    unittest.main()
