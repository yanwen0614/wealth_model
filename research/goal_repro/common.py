"""goal_repro 公共：R1 产物加载 + 常量（R2/R3 共用，禁各自硬编码）。"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from backtest.cnn_adapter.common import UNIFIED_FEES

HERE = os.path.dirname(os.path.abspath(__file__))
R1 = os.path.join(HERE, "runs", "r1")
PARQUET = "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"
FEES: dict[str, float] = dict(UNIFIED_FEES)
IDENT = {"model_name": "r1_hgb16", "checkpoint": "hgb200", "bins_version": "close5d",
         "eval_script_version": "goal_repro"}
FOLDS = ("fold1", "fold2")

__all__ = ["FEES", "FOLDS", "HERE", "IDENT", "PARQUET", "R1", "load_r1_preds"]


def load_r1_preds(fold: str) -> dict:
    """读 R1 preds 并过滤末日不可执行信号（无 T+1 行情），返回对齐四键字典。"""
    preds = dict(np.load(os.path.join(R1, f"preds_{fold}.npz"), allow_pickle=True))
    dates = pd.to_datetime(np.asarray(preds["dates"]))
    mkt_max = pd.to_datetime(
        pd.read_parquet(PARQUET, columns=["kline_time"])["kline_time"]).max()
    keep = dates < mkt_max
    print(f"[{fold}] signals={len(dates)} kept={int(keep.sum())}", flush=True)
    return {k: np.asarray(v)[keep] for k, v in preds.items()}
