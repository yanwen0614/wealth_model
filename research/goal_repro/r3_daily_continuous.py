"""R3 连续性消融：同一 R1 preds，target 日频下 buffer=0（纯日切）vs buffer=500（惯性持有）。

回答 goal chain-3 问题：连续持仓惯性是否优于每日硬切。产物落 runs/r3/metrics.json。
用法：uv run --project . --no-sync python research/goal_repro/r3_daily_continuous.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backtest.cnn_adapter.runner import run_cnn_backtest
from research.goal_repro.r2_account_backtest import FEES, IDENT, PARQUET, R1

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", "r3")


def main() -> None:
    mkt_max = pd.to_datetime(
        pd.read_parquet(PARQUET, columns=["kline_time"])["kline_time"]).max()
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for fold in ("fold1", "fold2"):
        preds = dict(np.load(os.path.join(R1, f"preds_{fold}.npz"), allow_pickle=True))
        dates = pd.to_datetime(np.asarray(preds["dates"]))
        keep = dates < mkt_max
        preds = {k: np.asarray(v)[keep] for k, v in preds.items()}
        fold_out = {}
        for tag, buf in (("daily_hard", 0), ("inertia500", 500)):
            outcome = run_cnn_backtest(pred_cache=preds, parquet_path=PARQUET, mode="target",
                                       initial_capital=2_000_000.0, target_size=100,
                                       sell_buffer=buf, strong_buy_threshold=0.0,
                                       **FEES, **IDENT)
            m = outcome.account_evaluation
            fold_out[tag] = {"annual": m.get("annualized_return"), "sharpe": m.get("sharpe"),
                             "mdd": m.get("max_drawdown"),
                             "final_nav": 2_000_000.0 * (1 + m["total_return"])}
            print(f"[{fold} {tag}] annual={m.get('annualized_return', 0):.4f} "
                  f"sharpe={m.get('sharpe', 0):.3f} mdd={m.get('max_drawdown', 0):.4f}",
                  flush=True)
        summary[fold] = fold_out
    with open(os.path.join(OUT, "metrics.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"saved {OUT}", flush=True)


if __name__ == "__main__":
    main()
