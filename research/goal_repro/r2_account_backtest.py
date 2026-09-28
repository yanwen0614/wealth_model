"""R2 可交易复现：R1 HGB preds → cnn_adapter（统一实盘费用）→ 账户指标。

rolling topN + target 双模式；费用=CLI统一口径（显式传入，与 core 默认对齐）；
产物落 runs/r2/metrics.json。用法：
uv run --project . --no-sync python research/goal_repro/r2_account_backtest.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backtest.cnn_adapter.runner import run_cnn_backtest, write_cnn_result

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.join(HERE, "runs", "r1")
OUT = os.path.join(HERE, "runs", "r2")
PARQUET = "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"
FEES = {"commission_rate_buy": 0.0002, "commission_rate_sell": 0.0002,
        "min_commission": 5.0, "stamp_tax_rate": 0.0005, "transfer_fee_rate": 0.00001}
IDENT = {"model_name": "r1_hgb16", "checkpoint": "hgb200", "bins_version": "close5d",
         "eval_script_version": "goal_repro@r2"}


def run_all() -> dict:
    os.makedirs(OUT, exist_ok=True)
    mkt_max = pd.to_datetime(
        pd.read_parquet(PARQUET, columns=["kline_time"])["kline_time"]).max()
    summary = {}
    for fold in ("fold1", "fold2"):
        preds = dict(np.load(os.path.join(R1, f"preds_{fold}.npz"), allow_pickle=True))
        dates = pd.to_datetime(np.asarray(preds["dates"]))
        keep = dates < mkt_max  # 末日信号无 T+1 可执行，边界过滤（方法学正确）
        preds = {k: np.asarray(v)[keep] for k, v in preds.items()}
        print(f"[{fold}] signals={len(dates)} kept={int(keep.sum())}", flush=True)
        fold_out = {}
        for topn in (10, 50):
            outcome = run_cnn_backtest(pred_cache=preds, parquet_path=PARQUET, top_n=topn,
                                       mode="rolling", initial_capital=2_000_000.0,
                                       **FEES, **IDENT)
            write_cnn_result(outcome, os.path.join(OUT, fold, f"rolling_top{topn}"))
            m = outcome.account_evaluation
            fold_out[f"rolling_top{topn}"] = {
                "annual": m.get("annualized_return"), "sharpe": m.get("sharpe"),
                "mdd": m.get("max_drawdown"), "final_nav": 2_000_000.0 * (1 + m["total_return"]),
                "config_hash": outcome.config_hash}
            print(f"[{fold} top{topn}] annual={m.get('annualized_return', 0):.4f} "
                  f"sharpe={m.get('sharpe', 0):.3f} mdd={m.get('max_drawdown', 0):.4f}", flush=True)
        outcome = run_cnn_backtest(pred_cache=preds, parquet_path=PARQUET, mode="target",
                                   initial_capital=2_000_000.0, target_size=100,
                                   sell_buffer=500, strong_buy_threshold=0.0, **FEES, **IDENT)
        write_cnn_result(outcome, os.path.join(OUT, fold, "target_s100"))
        m = outcome.account_evaluation
        fold_out["target_s100"] = {
            "annual": m.get("annualized_return"), "sharpe": m.get("sharpe"),
            "mdd": m.get("max_drawdown"), "final_nav": 2_000_000.0 * (1 + m["total_return"]),
            "config_hash": outcome.config_hash}
        print(f"[{fold} target] annual={m.get('annualized_return', 0):.4f} "
              f"sharpe={m.get('sharpe', 0):.3f} mdd={m.get('max_drawdown', 0):.4f}", flush=True)
        summary[fold] = fold_out
    with open(os.path.join(OUT, "metrics.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"saved {OUT}", flush=True)
    return summary


if __name__ == "__main__":
    run_all()
