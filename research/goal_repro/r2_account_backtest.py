"""R2 可交易复现：R1 HGB preds → cnn_adapter（统一实盘费用）→ 账户指标。

rolling topN + target 双模式；费用=CLI统一口径（显式传入，与 core 默认对齐）；
产物落 runs/r2/metrics.json。用法：
uv run --project . --no-sync python research/goal_repro/r2_account_backtest.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from backtest.cnn_adapter.runner import run_cnn_backtest, write_cnn_result
from research.goal_repro.common import FEES, FOLDS, IDENT, PARQUET, load_r1_preds

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", "r2")


def run_all() -> dict:
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for fold in FOLDS:
        preds = load_r1_preds(fold)
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
