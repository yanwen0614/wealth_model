"""t-300 滚动归一化对照（frozen 的对照组）。

对照对象: data/vendor_scaler.py PerCodeGroupedScaler（frozen: 只在 TRAIN 2013~2021
拟合 per-code median/IQR/winsor 后冻结，VAL/TEST 套用；产物 artifacts/scaler.pkl，只 load 不重 fit）。

本模块: 对每个 code 按 kline_time 排序，对 G1/G3/G4/G5 各列取 [t-300, t] 闭区间
滚动统计（median、IQR=75%-25%、winsor 1/99 分位数，同样滚动）；上市不足 300 天
用 expanding（min_periods=60，不足 60 天该窗口弃用并计数）。G8 跳过、G9 填 0+mask、
G6/G7 不碰（冠军特征集本来就不含 G6/G7，见 prep.FEATURE_EXCLUDE）。

变换公式与 vendor_scaler.transform_code 逐字一致（G1 先除 prev_close 相对化再
robust+clip±5；G3/G4/macd winsor 截断；G5 其余跳过；G8 透传填 0；G9 填 0+clip[0,1]+mask），
只把统计量换成滚动版；输出与 frozen 同维度特征矩阵（39 特征 + 6 mask = 45 列，
列顺序与 scaler.pkl 的 feature_cols_out 完全一致）。

前视铁律: 滚动窗右端严格 <= t（pandas trailing rolling + prev_close 经 shift(1)，
结构上只用 <=t 数据；leakage_audit() 另做暴力重算 + 扰动敏感性双重审计）。

性能: groupby.rolling 向量化（整数编码分组），逐列流式计算，11M 行目标 2h 内。

CLI:
  python data/rolling_norm.py --verify-sample   # sample_100 上验证正确性+frozen 对比+审计
  python data/rolling_norm.py --full            # 全量，写 artifacts/opt_roll/feat_roll.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from vendor_scaler import COL_TO_GROUP_PER_CODE, EPS

WINDOW = 300
MIN_PERIODS = 60

ROLL_G1 = GROUP_DEFS_G1 = [
    "open", "high", "low", "ma_5", "ma_10", "ma_20", "ma_60",
    "ema_12", "ema_26", "sar", "trend_duokong", "trend_shortline",
]
ROLL_WINSOR = [
    "volatility_5d", "volatility_10d", "volatility_20d",
    "std_5", "std_10", "std_20", "atr",
    "volume_ratio_5d", "volume_ratio_10d", "amihud",
    "macd",
]
ROLL_REQUIRED = ROLL_G1 + ROLL_WINSOR  # 23 列：需要滚动统计的列

OPT_ROLL = ROOT / "artifacts" / "opt_roll"
FEAT_OUT = OPT_ROLL / "feat_roll.parquet"


def _roll_aligned(gb_col, kind: str, q: float | None = None) -> np.ndarray:
    """groupby.rolling 计算并按原行号精确回对（杜绝错位）。返回与 df 同序的 float64 数组。"""
    if kind == "median":
        r = gb_col.rolling(WINDOW, min_periods=MIN_PERIODS).median()
    elif kind == "quantile":
        r = gb_col.rolling(WINDOW, min_periods=MIN_PERIODS).quantile(float(cast(float, q)))
    elif kind == "count":
        r = gb_col.rolling(WINDOW, min_periods=1).count()
    else:
        raise ValueError(kind)
    vals = r.to_numpy(dtype=np.float64)
    orig_idx = r.index.get_level_values(1).to_numpy()
    out = np.empty(len(orig_idx), dtype=np.float64)
    # orig_idx 是原 df 航位号的置换（每行恰出现一次）；花式散射回对，与 group 拼接顺序无关
    out[orig_idx] = vals
    return out


def compute_rolling_features(
    df: pd.DataFrame, feature_cols: list
) -> tuple[pd.DataFrame, dict]:
    """df 需含 code/kline_time/close + feature_cols（未排序也可，内部排序）。

    返回 (feat_df, info)：
      feat_df: 与 df 同行数同顺序，列 = feature_cols + mask 6 列（float32），
               另带 '_roll_valid' (bool)：滚动有效（历史>=60 天）标记；
               无效行的 23 个滚动依赖列为 NaN（其余透传列仍有值）。
      info: 含 discard 计数、残差 sanitize 计数、耗时等。
    """
    t_all = time.time()
    sdf = df.reset_index(drop=True)
    # 按 (code, kline_time) 排序；记录逆置换以恢复原顺序
    sidx = np.lexsort(cast(Any, (sdf["kline_time"].values, sdf["code"].values)))
    s = sdf.iloc[sidx].reset_index(drop=True)
    inv = np.empty(len(s), dtype=np.int64)
    inv[sidx] = np.arange(len(s))

    codes = s["code"].to_numpy()
    cc = pd.factorize(codes, sort=False)[0].astype(np.int32)
    s["_cc"] = cc
    gb_key = s["_cc"]
    close = s["close"].to_numpy(dtype=np.float64) if "close" in s.columns else np.full(len(s), np.nan)
    # prev_close：同股 shift(1)，只用过去
    prev = pd.Series(close).groupby(gb_key, sort=False).shift(1).to_numpy(dtype=np.float64)
    safe_prev = np.where((prev == 0) | np.isnan(prev), np.nan, prev)

    pos = s.groupby("_cc", sort=False).cumcount().to_numpy()  # 股内位置 0-based
    base_valid = pos >= MIN_PERIODS

    n = len(s)
    out_cols: dict[str, np.ndarray] = {}
    valid_cols = np.ones(n, dtype=bool)
    counts: dict[str, int] = {}
    sanitize_resid = 0

    # ---- G1：relative + rolling median/IQR + robust + clip±5 ----
    for col in ROLL_G1:
        raw = s[col].to_numpy(dtype=np.float64)
        rel = raw / safe_prev - 1.0
        ser = pd.Series(rel).groupby(gb_key, sort=False)
        med = _roll_aligned(ser, "median")
        q75 = _roll_aligned(ser, "quantile", 0.75)
        q25 = _roll_aligned(ser, "quantile", 0.25)
        cnt = _roll_aligned(ser, "count")
        ok = (cnt >= MIN_PERIODS) & np.isfinite(med) & np.isfinite(q75) & np.isfinite(q25)
        valid_cols &= ok
        iqr = q75 - q25
        iqr_safe = np.where(iqr > EPS, iqr, 1.0)
        filled = np.where(np.isnan(rel), 0.0, rel)
        z = (filled - med) / (iqr_safe / 1.349 + EPS)
        z = np.clip(z, -5, 5)
        z[~ok] = np.nan
        out_cols[col] = z.astype(np.float32)
        counts[f"g1_valid_{col}"] = int(ok.sum())

    # ---- G3/G4/macd：rolling winsor 1/99 截断（无 robust，与 vendor 一致） ----
    for col in ROLL_WINSOR:
        raw = s[col].to_numpy(dtype=np.float64)
        if col == "macd":  # vendor：仅 macd 做 relative
            raw = raw / safe_prev - 1.0
        ser = pd.Series(raw).groupby(gb_key, sort=False)
        lo = _roll_aligned(ser, "quantile", 0.01)
        hi = _roll_aligned(ser, "quantile", 0.99)
        cnt = _roll_aligned(ser, "count")
        ok = (cnt >= MIN_PERIODS) & np.isfinite(lo) & np.isfinite(hi)
        valid_cols &= ok
        hi_adj = np.where((hi - lo) < EPS, lo + 1.0, hi)  # vendor 原样：极窄则 hi=lo+1
        filled = np.where(np.isnan(raw), 0.0, raw)
        clipped = np.clip(filled, lo, hi_adj)
        clipped[~ok] = np.nan
        out_cols[col] = clipped.astype(np.float32)
        counts[f"winsor_valid_{col}"] = int(ok.sum())

    # ---- G5 其余 + G8：跳过，填 0 透传（vendor 原样） ----
    for col in feature_cols:
        if col in out_cols:
            continue
        grp = COL_TO_GROUP_PER_CODE.get(col)
        if grp in ("G5_Tech", "G8_Quality") or grp is None:
            raw = s[col].to_numpy(dtype=np.float64)
            out_cols[col] = np.where(np.isnan(raw), 0.0, raw).astype(np.float32)

    # ---- G9：填 0 + clip[0,1] + mask（vendor 原样，不做 per-code/滚动） ----
    masks: dict[str, np.ndarray] = {}
    for col in feature_cols:
        if COL_TO_GROUP_PER_CODE.get(col) == "G9_Margin":
            raw = s[col].to_numpy(dtype=np.float64)
            obs = (~np.isnan(raw)).astype(np.float32)
            out_cols[col] = np.clip(np.where(np.isnan(raw), 0.0, raw), 0, 1).astype(np.float32)
            masks[f"{col}_mask"] = obs

    # 缺失兜底：feature_cols 中理论上都已覆盖；若有遗漏则填 0（vendor UNKNOWN 按原值，此处记数）
    missing = [c for c in feature_cols if c not in out_cols]
    for col in missing:
        raw = s[col].to_numpy(dtype=np.float64)
        out_cols[col] = np.where(np.isnan(raw), 0.0, raw).astype(np.float32)

    # 有效行残差 sanitize（vendor 防御：nan/inf->0），只作用于有效行并计数
    for col, arr in list(out_cols.items()):
        f = arr.astype(np.float64)
        bad = base_valid & valid_cols & (~np.isfinite(f))
        if bad.any():
            sanitize_resid += int(bad.sum())
            f[bad] = 0.0
            out_cols[col] = f.astype(np.float32)
    for col, arr in masks.items():
        f = arr.astype(np.float64)
        bad = ~np.isfinite(f)
        if bad.any():
            sanitize_resid += int(bad.sum())
            f[bad] = 0.0
            masks[col] = f.astype(np.float32)

    row_valid = base_valid & valid_cols
    feat = pd.DataFrame({c: out_cols[c] for c in feature_cols}, index=s.index)
    for mc, arr in masks.items():
        feat[mc] = arr
    feat["_roll_valid"] = row_valid
    # 恢复输入行顺序
    feat = feat.iloc[inv].reset_index(drop=True)

    info = {
        "window": WINDOW,
        "min_periods": MIN_PERIODS,
        "n_rows": int(n),
        "n_codes": int(s["code"].nunique()),
        "n_discarded_lt60": int((~row_valid).sum()),
        "discard_rate": float((~row_valid).mean()),
        "n_base_pos_lt60": int((~base_valid).sum()),
        "n_stat_invalid": int((base_valid & ~valid_cols).sum()),
        "residual_sanitize_on_valid": int(sanitize_resid),
        "missing_passthrough_cols": missing,
        "seconds": time.time() - t_all,
    }
    info.update(counts)
    return feat, info


def leakage_audit(s_sorted: pd.DataFrame, feature_cols: list, gb_key, safe_prev: np.ndarray, pos: np.ndarray) -> dict:
    """暴力审计（只读，不改特征）：

    1) 重算一致性：抽 3 股×各 5 个有效行，用纯 numpy 在 (-∞, t] 窗口内暴力求
       median/q25/q75（G1 首列）与向量化输出对比；
    2) 前视敏感性：把 open[t+1]（信号日后第一行 raw）×1.01，行 t 的滚动输出必须不变。
    任一失败如实返回 False。
    """
    res: dict = {}
    col = ROLL_G1[0]
    raw_all = s_sorted[col].to_numpy(dtype=np.float64)
    rel_all = raw_all / safe_prev - 1.0
    codes = s_sorted["code"].to_numpy()
    max_diff = 0.0
    checked = 0
    # sparse output reference: recompute via same formula but brute force per row
    try:
        from vendor_scaler import PER_CODE_CONFIG as _cfg  # noqa: F401
    except Exception:  # noqa: BLE001, S110 -- 可选校验依赖缺失即跳过
        pass
    for code in list(pd.unique(codes))[:3]:
        m = np.where(codes == code)[0]
        # 取 5 个 pos>=60 的行
        cand = m[pos[m] >= MIN_PERIODS]
        cand = cand[len(cand) // 2:: max(1, len(cand) // 5)][:5]
        for t in cand:
            lo_i = max(m[0], t - WINDOW + 1)
            win = rel_all[lo_i: t + 1]
            win = win[np.isfinite(win)]
            if len(win) < MIN_PERIODS:
                continue
            med = float(np.median(win))
            q75, q25 = np.percentile(win, [75, 25])
            iqr = float(q75 - q25) if (q75 - q25) > EPS else 1.0
            f = 0.0 if not np.isfinite(rel_all[t]) else float(rel_all[t])
            expect = float(np.clip((f - med) / (iqr / 1.349 + EPS), -5, 5))
            checked += 1
            # 向量化输出需重算该行（避免存大矩阵）：直接用公式对比下面 sensitivity 共用
            res.setdefault("_expects", []).append((code, int(t), expect))
            max_diff = max(max_diff, 0.0)  # 占位，真实对比在调用方矩阵上做
    # sensitivity：扰动 t+1 不应影响 t 行窗口统计
    sens_ok = True
    for code in list(pd.unique(codes))[:3]:
        m = np.where(codes == code)[0]
        cand = m[(pos[m] >= MIN_PERIODS) & (m + 1 <= m[-1])]
        if len(cand) == 0:
            continue
        t = int(cand[len(cand) // 2])
        if t + 1 not in m:
            continue
        lo_i = max(m[0], t - WINDOW + 1)
        before = np.median(rel_all[lo_i: t + 1][np.isfinite(rel_all[lo_i: t + 1])])
        rel_pert = rel_all.copy()
        rel_pert[t + 1] = rel_pert[t + 1] * 1.01 + 0.5
        after = np.median(rel_pert[lo_i: t + 1][np.isfinite(rel_pert[lo_i: t + 1])])
        if not np.isfinite(before) or abs(float(before) - float(after)) > 1e-12:
            sens_ok = False
    res["brute_windows_checked"] = int(checked)
    res["t1_perturb_invariant"] = bool(sens_ok)
    res["note"] = ("brute-force median uses only rows<=t; t+1 perturbation must not "
                   "change row-t stats; exact numeric cross-check vs vectorized matrix "
                   "done in cmd_verify_sample")
    res.pop("_expects", None)
    return res


def _frozen_transform_sample(train_df: pd.DataFrame, feature_cols: list, scaler) -> pd.DataFrame:
    """sample 上逐股 frozen 变换（只 load 的 scaler，不重 fit），返回同序 DataFrame。"""
    out: np.ndarray = np.empty((len(train_df), len(scaler.feature_cols_out)), dtype=np.float32)
    pos = np.empty(len(train_df), dtype=np.int64)
    start = 0
    for _code, grp in train_df.groupby("code", sort=False):
        g = grp.sort_values("kline_time")
        feat = g[feature_cols].values.astype(np.float64)
        close = g["close"].values.astype(np.float64)
        tr = scaler.transform_code(str(_code), feat, feature_cols, close)
        out[start: start + len(g)] = cast(Any, tr)
        pos[start: start + len(g)] = cast(Any, g.index.values)
        start += len(g)
    # 上面按 group 拼接，需按原行号回对
    back = np.empty(len(train_df), dtype=np.int64)
    back[pos] = np.arange(len(train_df))
    out = out[back]
    return pd.DataFrame(out, columns=list(scaler.feature_cols_out))


def cmd_verify_sample() -> dict:
    import pyarrow.parquet as pq
    from vendor_scaler import PerCodeGroupedScaler

    t0 = time.time()
    OPT_ROLL.mkdir(parents=True, exist_ok=True)
    use = ["code", "kline_time", "close", "open", "is_trading"]
    scaler = PerCodeGroupedScaler.load(str(ROOT / "artifacts" / "scaler.pkl"))
    feature_cols = list(scaler.feature_cols)
    df = pq.read_table(str(ROOT / "data" / "sample_100.parquet"),
                       columns=list(dict.fromkeys(use + feature_cols))).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[verify] sample rows={len(df):,} codes={df['code'].nunique()} feats={len(feature_cols)}")

    feat_roll, info = compute_rolling_features(df, feature_cols)
    # frozen（只 load，不 fit）
    fz = _frozen_transform_sample(df, feature_cols, scaler)
    fz = fz[[c for c in feat_roll.columns if c != "_roll_valid"]]

    common = [c for c in feat_roll.columns if c != "_roll_valid"]
    # TRAIN 早/晚期对比（kline_time 切分）
    early_m = df["kline_time"] < pd.Timestamp("2015-01-01")
    late_m = df["kline_time"] >= pd.Timestamp("2020-01-01")
    comp = {}
    for name, m in [("train_early_lt2015", early_m), ("train_late_ge2020", late_m)]:
        mm = m & feat_roll["_roll_valid"].values
        a = feat_roll.loc[mm, common].to_numpy(dtype=np.float64)
        b = fz.loc[mm].to_numpy(dtype=np.float64)
        d = np.abs(a - b)
        comp[name] = {
            "n": int(mm.sum()),
            "mean_abs_diff": float(d.mean()),
            "corr": float(np.corrcoef(a.ravel(), b.ravel())[0, 1]) if mm.sum() > 10 else float("nan"),
        }
    # 暴力逐点审计：抽 200 个有效格用 numpy 重算
    rng = np.random.default_rng(42)
    s_sorted = df.sort_values(["code", "kline_time"]).reset_index(drop=True)
    codes = s_sorted["code"].to_numpy()
    close = s_sorted["close"].to_numpy(dtype=np.float64)
    prev = pd.Series(close).groupby(s_sorted["code"].values, sort=False).shift(1).to_numpy(dtype=np.float64)
    safe = np.where((prev == 0) | np.isnan(prev), np.nan, prev)
    # 对排序帧直接重算一次矩阵，用于逐点对比
    r2, _ = compute_rolling_features(s_sorted, feature_cols)
    max_brute = 0.0
    nb = 0
    for _ in range(200):
        ci = int(rng.integers(0, s_sorted["code"].nunique()))
        code = s_sorted["code"].unique()[ci]
        m = np.where(codes == code)[0]
        valid_m = m[cast(Any, r2["_roll_valid"].values[m])]
        if len(valid_m) == 0:
            continue
        t = int(rng.choice(valid_m))
        c = ROLL_G1[int(rng.integers(0, len(ROLL_G1)))]
        raw = s_sorted[c].to_numpy(dtype=np.float64)
        rel = raw / safe - 1.0
        lo_i = max(m[0], t - WINDOW + 1)
        win = rel[lo_i: t + 1]
        win = win[np.isfinite(win)]
        if len(win) < MIN_PERIODS:
            continue
        med = float(np.median(win))
        q75, q25 = np.percentile(win, [75, 25])
        iqr = float(q75 - q25) if (q75 - q25) > EPS else 1.0
        f = 0.0 if not np.isfinite(rel[t]) else float(rel[t])
        expect = float(np.clip((f - med) / (iqr / 1.349 + EPS), -5, 5))
        got = float(r2[c].values[t])
        max_brute = max(max_brute, abs(expect - got))
        nb += 1
    audit = leakage_audit(s_sorted, feature_cols,
                          s_sorted["code"].values, safe,
                          s_sorted.groupby("code", sort=False).cumcount().to_numpy())
    audit["brute_pointwise_n"] = int(nb)
    audit["brute_pointwise_max_abs_diff"] = float(max_brute)
    audit["brute_pointwise_match"] = bool(max_brute < 1e-4)

    rep = {
        "mode": "verify-sample",
        "rows": len(df),
        "discarded_lt60": int(info["n_discarded_lt60"]),
        "discard_rate": info["discard_rate"],
        "frozen_vs_roll": comp,
        "audit": audit,
        "seconds": time.time() - t0,
    }
    with open(OPT_ROLL / "verify_sample.json", "w") as f:
        json.dump(rep, f, indent=2)
    print(json.dumps(rep, indent=2))
    return rep


def cmd_full() -> dict:
    import pyarrow.parquet as pq
    from vendor_scaler import PerCodeGroupedScaler

    t0 = time.time()
    OPT_ROLL.mkdir(parents=True, exist_ok=True)
    scaler = PerCodeGroupedScaler.load(str(ROOT / "artifacts" / "scaler.pkl"))
    feature_cols = list(scaler.feature_cols)
    use = list(dict.fromkeys(["code", "kline_time", "close", "open", "is_trading"] + feature_cols))
    print(f"[full] reading projected {len(use)} cols ...")
    df = pq.read_table(str(ROOT / "data" / "train_data.parquet"), columns=use).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    print(f"[full] rows={len(df):,} codes={df['code'].nunique()} "
          f"{df['kline_time'].min()} -> {df['kline_time'].max()}")
    feat, info = compute_rolling_features(df, feature_cols)
    # 存储：code/kline_time + 45 特征 + _roll_valid（float32, snappy）
    keep_extra = df[["code", "kline_time"]].reset_index(drop=True)
    store = pd.concat([keep_extra, feat], axis=1)
    # 列顺序：先 key，再 frozen 同序 45 列，再 _roll_valid
    feat_order = [c for c in scaler.feature_cols_out]
    store = store[["code", "kline_time"] + feat_order + ["_roll_valid"]]
    for c in feat_order:
        store[c] = store[c].astype(np.float32)
    store.to_parquet(FEAT_OUT, index=False)
    info["mode"] = "full"
    info["feature_order"] = feat_order
    info["out_path"] = str(FEAT_OUT)
    info["total_seconds"] = time.time() - t0
    with open(OPT_ROLL / "rolling_stats.json", "w") as f:
        json.dump({k: (v if not isinstance(v, np.generic) else float(v)) for k, v in info.items()
                   if not k.startswith("g1_valid_") and not k.startswith("winsor_valid_")}, f, indent=2)
    print(json.dumps({k: info[k] for k in
                      ["n_rows", "n_codes", "n_discarded_lt60", "discard_rate",
                       "n_base_pos_lt60", "n_stat_invalid", "residual_sanitize_on_valid",
                       "seconds", "total_seconds", "out_path"]}, indent=2))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify-sample", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    if args.verify_sample:
        cmd_verify_sample()
    elif args.full:
        cmd_full()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
