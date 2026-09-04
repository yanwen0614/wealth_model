"""Step0 全量 bins 分位重算（离线脚本，不碰训练主链路）.

口径与 data/dataset.py 一致:
- is_trading=True 过滤，按 code,kline_time 排序
- future_ret[t] = close[t+5]/close[t]-1（dataset.py:259-272，仅 close 均有效且 close[t]!=0）
- digitize: np.digitize(future_ret, bins) -> 0..len(bins)（dataset.py:306）

双口径:
- ALL_RET: 全部有效 t (t in [0, n-horizon)) 的 future_ret
- WIN_LABEL: seq_len=60 窗口末日标签 y=future_ret[s+59], s in [0, n-seq-horizon]（dataset.py:274-290）

候选 bins（均不写回 train.py:34 默认，仅输出报告冻结 11 类候选）:
- bins52: linspace(-0.25, 0.25, 51)（现行默认，52 类）
- bins11_trading: [-15,-10,-6,-3,-1,1,3,6,10,15]/100（冻结候选，11 类）
- bins13_trading: bins11 + ±25bp 外层（13 类）
- bins15_trading: bins13 + ±20bp（15 类）
- bins11_quantile: WIN_LABEL 口径 k/11 分位（k=1..10，11 类，等频对照）

输出 logs/bins_quantile.json + stdout 对照表（每类占比、熵 eff、tail）.

用法:
    uv run --project . python scripts/recompute_bins.py --max_codes 20   # 快速验证
    uv run --project . python scripts/recompute_bins.py                   # 全量
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pyarrow.parquet as pq

HORIZON = 5
SEQ_LEN = 60

BINS52 = (np.linspace(-25, 25, 51) / 100).tolist()
BINS11_TRADING = [-0.15, -0.10, -0.06, -0.03, -0.01, 0.01, 0.03, 0.06, 0.10, 0.15]
BINS13_TRADING = [-0.25, -0.15, -0.10, -0.06, -0.03, -0.01, 0.01, 0.03, 0.06, 0.10, 0.15, 0.25]
BINS15_TRADING = [-0.25, -0.20, -0.15, -0.10, -0.06, -0.03, -0.01,
                  0.01, 0.03, 0.06, 0.10, 0.15, 0.20, 0.25]


def resolve_parquet(pattern: str) -> str:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"未找到 parquet: {pattern}")
    return paths[0]


def future_ret_close(close: np.ndarray, horizon: int) -> np.ndarray:
    """与 dataset.py:259-272 同口径（向量化等价实现）。"""
    n = len(close)
    fr = np.full(n, np.nan, dtype=np.float64)
    valid = ~np.isnan(close)
    c0 = close[:-horizon]
    c1 = close[horizon:]
    ok = valid[:-horizon] & valid[horizon:] & (c0 != 0)
    fr_vals = np.full(len(c0), np.nan)
    fr_vals[ok] = c1[ok] / c0[ok] - 1.0
    fr[: n - horizon] = fr_vals
    return fr


def collect_returns(parquet_path: str, horizon: int, seq_len: int, max_codes: int | None = None):
    """返回 (all_ret, win_label) 两个一维 float64 数组。"""
    table = pq.read_table(parquet_path, columns=["code", "kline_time", "close", "is_trading"])
    df = table.to_pandas()
    df = df[df["is_trading"] == True]
    df["kline_time"] = df["kline_time"].astype("datetime64[ns]")
    df = df.sort_values(["code", "kline_time"]).reset_index(drop=True)
    codes = df["code"].unique()
    if max_codes is not None and len(codes) > max_codes:
        df = df[df["code"].isin(codes[:max_codes])]
        print(f"[recompute_bins] max_codes={max_codes}, 行数 {len(df):,}")
    else:
        print(f"[recompute_bins] 行数 {len(df):,}, 股票数 {len(codes)}")
    all_parts, win_parts = [], []
    for _code, g in df.groupby("code", sort=False):
        close = g["close"].to_numpy(dtype=np.float64)
        n = len(close)
        if n < seq_len + horizon:
            continue
        fr = future_ret_close(close, horizon)
        all_parts.append(fr[~np.isnan(fr)])
        max_s = n - seq_len - horizon + 1
        if max_s > 0:
            label_pos = np.arange(seq_len - 1, seq_len - 1 + max_s)
            lab = fr[label_pos]
            win_parts.append(lab[~np.isnan(lab)])
    all_ret = np.concatenate(all_parts) if all_parts else np.array([], dtype=np.float64)
    win_label = np.concatenate(win_parts) if win_parts else np.array([], dtype=np.float64)
    print(f"[recompute_bins] ALL_RET n={len(all_ret):,}, WIN_LABEL n={len(win_label):,}")
    return all_ret, win_label


def digitize_stats(values: np.ndarray, bins: list[float]) -> dict:
    """np.digitize 同 dataset.py:306 口径的分布统计（含熵 eff 与 tail）。"""
    b = np.array(bins, dtype=np.float64)
    if b.size == 0:
        raise ValueError("bins 为空")
    if not bool(np.all(np.diff(b) > 0)):
        raise ValueError("bins 必须单调递增")
    disc = np.digitize(values, b)  # 0..len(b)
    k = len(b) + 1
    counts = np.bincount(disc, minlength=k).astype(np.int64)
    total = int(counts.sum())
    ratio = (counts / total).tolist() if total else [0.0] * k
    p = counts / total if total else np.zeros(k)
    nz = p[p > 0]
    ent = float(-np.sum(nz * np.log(nz)))
    eff = float(ent / np.log(k)) if k > 1 else 0.0
    return {
        "num_classes": k,
        "bins": [float(x) for x in b],
        "counts": [int(c) for c in counts],
        "ratio": [float(r) for r in ratio],
        "min_ratio": float(np.min(p)) if total else 0.0,
        "edge_ratio": float(p[0] + p[-1]) if total else 0.0,
        "tail_lt_1pct": int(np.sum(p < 0.01)),
        "tail_lt_01pct": int(np.sum(p < 0.001)),
        "entropy": ent,
        "entropy_eff": eff,
        "n": total,
    }


def quantile_bins(values: np.ndarray, num_classes: int) -> list[float]:
    if values.size == 0:
        raise ValueError("quantile_bins 输入为空，无法求分位")
    qs = [(k / num_classes) for k in range(1, num_classes)]
    edges = np.quantile(values, qs).tolist()
    edges = sorted({round(float(x), 6) for x in edges})  # 去重防 digitize 空类
    return [float(x) for x in edges]


def print_row(name: str, caliber: str, st: dict) -> None:
    print(
        f"{name:>16} | {caliber:>9} | K={st['num_classes']:>2} "
        f"| ent_eff={st['entropy_eff']:.3f} | min={st['min_ratio'] * 100:6.3f}% "
        f"| edge={st['edge_ratio'] * 100:6.3f}% | <1%:{st['tail_lt_1pct']:>2} "
        f"<0.1%:{st['tail_lt_01pct']:>2}"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Step0 全量 bins 分位重算")
    ap.add_argument("--parquet", default="data/test/train_data/train_data_v1_*.parquet")
    ap.add_argument("--horizon", type=int, default=HORIZON)
    ap.add_argument("--seq_len", type=int, default=SEQ_LEN)
    ap.add_argument("--max_codes", type=int, default=None)
    ap.add_argument("--out", default="logs/bins_quantile.json")
    args = ap.parse_args()

    parquet_path = resolve_parquet(args.parquet)
    print(f"[recompute_bins] parquet={parquet_path} horizon={args.horizon} seq={args.seq_len}")
    all_ret, win_label = collect_returns(parquet_path, args.horizon, args.seq_len, args.max_codes)

    # 11 等频对照边界取自 WIN_LABEL 口径
    bins11_q = quantile_bins(win_label, 11)
    candidates: dict[str, list[float]] = {
        "bins52_linspace": BINS52,
        "bins11_trading": BINS11_TRADING,
        "bins13_trading": BINS13_TRADING,
        "bins15_trading": BINS15_TRADING,
        "bins11_quantile": bins11_q,
    }
    calibers = {"ALL_RET": all_ret, "WIN_LABEL": win_label}

    print("     candidate   |   caliber | stats")
    report: dict = {
        "parquet": parquet_path, "horizon": args.horizon, "seq_len": args.seq_len,
        "n_all_ret": len(all_ret), "n_win_label": len(win_label),
        "frozen_bins11_candidate": BINS11_TRADING, "candidates": {},
    }
    for name, bins in candidates.items():
        report["candidates"][name] = {"bins": [float(x) for x in bins], "stats": {}}
        for cal, vals in calibers.items():
            st = digitize_stats(vals, bins)
            report["candidates"][name]["stats"][cal] = st
            print_row(name, cal, st)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[recompute_bins] 报告已写入 {args.out}")
    print("[recompute_bins] 冻结 bins11 候选:", BINS11_TRADING)
    print("[recompute_bins] 说明: 不改 train.py:34 BINS 默认；11 类决策待 Step1 映射评估.")


if __name__ == "__main__":
    main()
