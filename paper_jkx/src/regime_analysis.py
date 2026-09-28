"""市况 regime x 周期(I5/I20/I60)环境切换验证(子代理C).

纯分析脚本:只读行情矩阵与已有 nav,不跑回测、不用 GPU。
输入 : paper_jkx/logs/ohlc_full_2019-2025.npz(预热)+ohlc_full_{2024,2025,2026}.npz
       paper_jkx/logs/backtest_{I5R5,I20R20,I60R60}_{2024,2025,2026}/nav_target100.npy
输出 : paper_jkx/logs/regime_2026/ (csv+json+png)
诚实性:所有 regime 指标只用 T 日及之前数据;上月末 regime 决定下月组合,可事先执行。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs"
OUT = LOG / "regime_2026"
GROUPS = ["I5R5", "I20R20", "I60R60"]
YEARS = ["2024", "2025", "2026"]
TREND_UP, TREND_DN = 0.03, -0.03  # 趋势阈值:收盘相对MA60偏离±3%
ANN = 242  # 年化因子


def daily_mret(path):
    """等权市场日收益(只用当日截面,因果无未来函数).零/负收盘视为缺失."""
    d = np.load(path)
    c = d["close_m"].astype(float)
    c = np.where(c > 0, c, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c[:, 1:] / c[:, :-1] - 1
    m = np.nanmean(r, axis=0)
    dt = pd.to_datetime([str(x) for x in d["dates"][1:]])
    return pd.Series(m, index=dt).replace([np.inf, -np.inf], np.nan)


def build_market():
    """拼接 2019~2025(预热)与 2026 日收益;组合宇宙变化已在文档声明."""
    hist = daily_mret(LOG / "ohlc_full_2019-2025.npz")
    y26 = daily_mret(LOG / "ohlc_full_2026.npz")
    y26 = y26[y26.index > hist.index.max()]
    return pd.concat([hist, y26]).sort_index().ffill().fillna(0.0)
def causal_indicators(mret):
    """因果指标:trend=P/MA60-1,vol=过去60日收益std年化;均只用<=T数据."""
    px = (1 + mret).cumprod()
    trend = px / px.rolling(60, min_periods=60).mean() - 1
    vol = mret.rolling(60, min_periods=60).std() * np.sqrt(ANN)
    me = px.resample("ME").last().pct_change()
    te = trend.resample("ME").last()
    ve = vol.resample("ME").last()
    return px, me, te, ve


def label_month(trend_prev, vol_prev, vol_med_prev):
    """上月末指标->本月 regime 标签(可事先执行)."""
    if pd.isna(trend_prev):
        return "未知", "未知"
    regime = "趋势上" if trend_prev > TREND_UP else ("趋势下" if trend_prev < TREND_DN else "震荡")
    vstate = "高波" if (not pd.isna(vol_prev) and vol_prev >= vol_med_prev) else "低波"
    return regime, vstate


def monthly_group_rets():
    """各组 target100 月收益;每年 nav 从 1.0 起算,跨年月收益链式拼接."""
    out = {}
    for g in GROUPS:
        s = None
        for y in YEARS:
            d = np.load(LOG / f"ohlc_full_{y}.npz")
            dt = pd.to_datetime([str(x) for x in d["dates"]])
            nav = np.load(LOG / f"backtest_{g}_{y}/nav_target100.npy")
            assert len(nav) == len(dt), (g, y, len(nav), len(dt))
            nav_s = pd.Series(nav, index=dt)
            mr = nav_s.resample("ME").last().pct_change()
            mr.iloc[0] = float(nav_s.iloc[nav_s.index.to_period("M") == nav_s.index[0].to_period("M")].iloc[-1] / 1.0 - 1)
            s = mr if s is None else pd.concat([s, mr])
        out[g] = s
    return pd.DataFrame(out)
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mret = build_market()
    _px, me, te, ve = causal_indicators(mret)
    vols_hist = ve[ve.index < "2024-01-01"].dropna()  # 仅2024前,作vol中位数种子
    grp = monthly_group_rets()
    months = pd.period_range("2024-01", "2026-08", freq="M")
    # R1 预注册映射(直觉先验,非样本内挑选):趋势上->I20,震荡->I60,趋势下->空仓
    R1 = {"趋势上": "I20R20", "震荡": "I60R60", "趋势下": "空仓"}
    rows = []
    for p in months:
        m_end = p.to_timestamp("M")
        prev = (p - 1).to_timestamp("M")
        tp = float(te[te.index <= prev].iloc[-1]) if (te.index <= prev).any() else np.nan
        vp = float(ve[ve.index <= prev].iloc[-1]) if (ve.index <= prev).any() else np.nan
        pool = pd.concat([vols_hist, ve[(ve.index < m_end) & (ve.index >= "2024-01-01")].dropna()])
        pool = pool[pool.index <= prev]
        vmed = float(pool.median())
        regime, vstate = label_month(tp, vp, vmed)
        r = {g: float(grp.loc[m_end, g]) for g in GROUPS}
        winner = max(r, key=r.get)
        pick = R1[regime]
        switch_r = 0.0 if pick == "空仓" else r[pick]
        rows.append({"month": str(p), "mkt_ret": float(me.loc[m_end]), "trend60_prev": tp,
                     "vol60_prev": vp, "vol_med_prev": vmed, "regime": regime, "vol_state": vstate,
                     "ret_I5": r["I5R5"], "ret_I20": r["I20R20"], "ret_I60": r["I60R60"],
                     "winner": winner, "R1_pick": pick, "R1_ret": switch_r})
    tab = pd.DataFrame(rows).set_index("month")
    tab.to_csv(OUT / "regime_monthly.csv", encoding="utf-8-sig")
    # regime x 组别对照:月均收益/链式累计/该 regime 下最优组命中
    agg = []
    for (rg, vs), sub in tab.groupby(["regime", "vol_state"]):
        row = {"regime": rg, "vol_state": vs, "n_months": len(sub)}
        for g, col in zip(GROUPS, ["ret_I5", "ret_I20", "ret_I60"]):
            row[f"{g}_mean"] = float(sub[col].mean())
            row[f"{g}_chained"] = float((1 + sub[col]).prod() - 1)
        row["winner_chained"] = max(GROUPS, key=lambda g: row[f"{g}_chained"])
        agg.append(row)
    agg_df = pd.DataFrame(agg)
    agg_df.to_csv(OUT / "regime_agg.csv", index=False, encoding="utf-8-sig")
    # 季度版(季度 regime 取季度内众数,仅描述性)
    q = tab.copy()
    q["q"] = pd.PeriodIndex(pd.to_datetime(q.index), freq="Q").astype(str)
    qtab = q.groupby("q").agg(mkt_ret=("mkt_ret", lambda x: float((1 + x).prod() - 1)),
                              regime=("regime", lambda x: x.mode().iloc[0]),
                              ret_I5=("ret_I5", lambda x: float((1 + x).prod() - 1)),
                              ret_I20=("ret_I20", lambda x: float((1 + x).prod() - 1)),
                              ret_I60=("ret_I60", lambda x: float((1 + x).prod() - 1)))
    qtab.to_csv(OUT / "regime_quarterly.csv", encoding="utf-8-sig")
    # 切换组合 vs 单组买入持有(均从2024-01起链式拼接月收益)
    nav = pd.DataFrame(index=tab.index)
    nav["R1_switch"] = (1 + tab["R1_ret"]).cumprod()
    for g, col in zip(GROUPS, ["ret_I5", "ret_I20", "ret_I60"]):
        nav[f"BH_{g}"] = (1 + tab[col]).cumprod()
    nav["MKT"] = (1 + tab["mkt_ret"]).cumprod()
    nav.to_csv(OUT / "switch_nav.csv", encoding="utf-8-sig")
    # 样本内最优映射上界(不可执行,仅标注过拟合上限)
    col_of = {"I5R5": "ret_I5", "I20R20": "ret_I20", "I60R60": "ret_I60"}
    best_map = {rg: max(GROUPS, key=lambda g: float((1 + sub[col_of[g]]).prod()))
                for rg, sub in tab.groupby("regime")}
    best_ret = tab.apply(lambda r_: r_[col_of[best_map[r_["regime"]]]], axis=1)
    summary = {
        "regime_def": "上月末因果指标:P/MA60-1>+3%趋势上,<-3%趋势下,其余震荡;高/低波按上月末vol60与此前全部月末vol中位数(膨胀中位数,因果)划分",
        "R1_rule": R1, "R1_note": "预注册直觉映射,非样本内挑选",
        "final_nav": {c: float(nav[c].iloc[-1]) for c in nav.columns},
        "total_ret": {c: float(nav[c].iloc[-1] - 1) for c in nav.columns},
        "R1_cash_months": int((tab["R1_pick"] == "空仓").sum()),
        "expost_best_map": best_map,
        "expost_best_nav": float((1 + best_ret).cumprod().iloc[-1]),
        "warnings": ["样本外 regime 仅3个年段32个月,结论按假设定级",
                     "2026宇宙5196股 vs 历史5166股,市场序列为近似拼接",
                     "2026文件26股出现0收盘已按缺失处理;2019-25与2026非交易日填充口径不一致"],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5))
    for c in nav.columns:
        ax.plot(pd.to_datetime(nav.index), nav[c], label=c)
    ax.axhline(1.0, color="k", lw=0.8)
    ax.set_title("R1 regime-switch vs buy-hold (monthly chained, 2024-01~2026-08)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "switch_nav.png", dpi=120)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
