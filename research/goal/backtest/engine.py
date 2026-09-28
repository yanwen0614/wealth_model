"""Independent lightweight backtester (no external project deps).

Logic (contract):
  - Input pred parquet schema: code:str, kline_time:datetime64, score:float,
    future_ret_5d:float, q_true:int (q_true unused by engine, kept for compat).
  - TEST segment = whole input file sorted by date (synthetic files are
    2024-01-01~2025-12-31 already; real pred_test.parquet is also TEST-only).
  - Rebalance every 5 trading days: rebalance dates = dates[0 : n_rb*5 : 5],
    where n_rb = len(dates)//5 (tail <5d dropped). At each rebalance date,
    cross-section split into Q1..Q5 by score quintile (pd.qcut, equal-weight),
    each sleeve's 5-day gross return = mean(future_ret_5d) of its members.
  - Sleeves tracked: Q5 long / Q1 long / market equal-weight benchmark
    (plus Q2..Q4 internally for the quintile bar chart).
  - Fees: buy 0.03% / sell 0.13%. Inception cost = 0.0003 on full notional.
    Subsequent cost = turnover * (0.0003+0.0013), turnover = 1 - overlap/qsize
    (fraction of names replaced). Benchmark holds all names -> turnover 0
    after inception (drift ignored), cost 0 thereafter.
  - Metrics: totals, annualization via 252 trading days, Sharpe with
    rf=0.02 (daily-compounded to 5-day periods), max drawdown (positive
    magnitude), IC mean/IR over ALL cross-sections (Spearman per date),
    mean Q5 turnover (ex-inception), n_rebalances, periods (=n_rb*5 days).

Outputs under <out>/:
  backtest.json (keys: q5_total,q5_annual,q5_sharpe,q5_maxdd,q1_total,
    q1_annual,bench_total,bench_annual,spread_annual,ic_mean,ic_ir,
    turnover,n_rebalances,periods)
  figs/equity.png (Q5/Q1/bench NAV)
  figs/quintile.png (Q1..Q5 annualized bars)

Usage:
  python engine.py --pred <parquet> --market <train_data.parquet> --out <dir>  # 默认 adapter 订单路径（G01 起）
  python engine.py --pred <parquet> --out <dir> --legacy  # 旧 quintile 体，须 GOAL_ALLOW_LEGACY=1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BUY_FEE = 0.0003
SELL_FEE = 0.0013
ROUNDTRIP = BUY_FEE + SELL_FEE
RF_ANNUAL = 0.02
TRADING_DAYS = 252
HOLD = 5

# OLD_LOGIC（阶段 3 G01）：以下 quintile 纸面引擎默认不可达；
# 复用须 --legacy + GOAL_ALLOW_LEGACY=1 双显式 opt-in；默认路径走 goal_adapter 订单引擎。
OLD_LOGIC = True


def compute_ic(df: pd.DataFrame) -> tuple[float, float]:
    """Per-section Spearman(score, future_ret_5d): mean and mean/std."""
    ics = df.groupby("kline_time")[["score", "future_ret_5d"]].apply(
        lambda g: g["score"].corr(g["future_ret_5d"], method="spearman")
    )
    ics = ics.dropna()
    # stub 把 mean/std 宽化为联合类型：内层 cast 收窄静态类型，外层 float()
    # 保留原语义（np 标量转 Python float，保证 backtest.json 可序列化）。
    mean = float(cast(float, ics.mean())) if len(ics) else 0.0
    std = float(cast(float, ics.std(ddof=1))) if len(ics) > 1 else 0.0
    ir = float(mean / std) if std > 0 else 0.0
    return mean, ir


def annualize(total_ret: float, n_days: int) -> float:
    nav = 1.0 + total_ret
    if nav <= 0 or n_days <= 0:
        return float("-inf")
    return float(nav ** (TRADING_DAYS / n_days) - 1.0)


def period_sharpe(period_rets: np.ndarray) -> float:
    """Annualized Sharpe from 5-day net returns; rf compounded to 5d."""
    if len(period_rets) < 2:
        return 0.0
    rf_p = (1.0 + RF_ANNUAL) ** (HOLD / TRADING_DAYS) - 1.0
    ex = period_rets - rf_p
    sd = ex.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(ex.mean() / sd * np.sqrt(TRADING_DAYS / HOLD))


def max_drawdown(nav: np.ndarray) -> float:
    """Positive magnitude, e.g. 0.15 = 15% peak-to-trough."""
    if len(nav) == 0:
        return 0.0
    peak = np.maximum.accumulate(nav)
    dd = (peak - nav) / np.maximum(peak, 1e-12)
    return float(np.max(dd))


def run_backtest(df: pd.DataFrame) -> dict:
    df = df.copy()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    df = df.sort_values("kline_time")
    # df 已按 kline_time 有序，drop_duplicates 保持该顺序，无需二次排序。
    dates = pd.DatetimeIndex(df["kline_time"].drop_duplicates())
    n_rb = len(dates) // HOLD
    if n_rb < 1:
        raise ValueError(f"not enough dates: {len(dates)}")
    use_dates = dates[: n_rb * HOLD]
    rb_dates = use_dates[0::HOLD]

    # Fast lookup: group rows by date once
    grouped = {d: g for d, g in df[df["kline_time"].isin(cast(Any, use_dates))].groupby("kline_time")}

    q_rets: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    bench_rets: list[float] = []
    q5_turnovers: list[float] = []
    q1_turnovers: list[float] = []
    prev_q5: set = set()
    prev_q1: set = set()

    for i, d in enumerate(rb_dates):
        g = grouped[d].copy()
        # quintile by score, equal-weight
        g["q"] = cast(Any, pd.qcut(g["score"], 5, labels=[1, 2, 3, 4, 5])).astype(int)
        for q in range(1, 6):
            members = g.loc[g["q"] == q]
            q_rets[q].append(float(cast(float, members["future_ret_5d"].mean())))
        bench_rets.append(float(cast(float, g["future_ret_5d"].mean())))

        cur_q5 = set(g.loc[g["q"] == 5, "code"].tolist())
        cur_q1 = set(g.loc[g["q"] == 1, "code"].tolist())
        if i == 0:
            q5_turnovers.append(1.0)  # full buy (recorded but excluded from mean)
            q1_turnovers.append(1.0)
        else:
            qsize = max(len(cur_q5), 1)
            q5_turnovers.append(1.0 - len(cur_q5 & prev_q5) / qsize)
            q1_turnovers.append(1.0 - len(cur_q1 & prev_q1) / max(len(cur_q1), 1))
        prev_q5, prev_q1 = cur_q5, cur_q1

    # Apply costs -> net period returns -> NAV
    def net_nav(gross: list[float], turnovers: list[float] | None) -> tuple[np.ndarray, np.ndarray]:
        gross_a = np.asarray(gross, dtype=float)
        if turnovers is None:  # benchmark: only inception buy fee
            costs = np.zeros_like(gross_a)
            costs[0] = BUY_FEE
        else:
            costs = np.zeros_like(gross_a)
            costs[0] = BUY_FEE
            costs[1:] = np.asarray(turnovers[1:]) * ROUNDTRIP
        net = gross_a - costs
        nav = np.cumprod(1.0 + net)
        return nav, net

    navs: dict[str, np.ndarray] = {}
    nets: dict[str, np.ndarray] = {}
    # Q5/Q1 use own measured turnover; Q2..Q4 (chart only) use the average
    # Q5 cost rate so the bar chart stays cost-consistent without extra books.
    avg_cost_rate = float(np.mean([t * ROUNDTRIP for t in q5_turnovers[1:]])) if n_rb > 1 else 0.0
    for q in range(1, 6):
        gross_a = np.asarray(q_rets[q], dtype=float)
        costs = np.zeros_like(gross_a)
        costs[0] = BUY_FEE
        if q == 5:
            costs[1:] = np.asarray(q5_turnovers[1:]) * ROUNDTRIP
        elif q == 1:
            costs[1:] = np.asarray(q1_turnovers[1:]) * ROUNDTRIP
        else:
            costs[1:] = avg_cost_rate
        net = gross_a - costs
        nets[f"q{q}"] = net
        navs[f"q{q}"] = np.cumprod(1.0 + net)
    nav_b, net_b = net_nav(bench_rets, None)
    navs["bench"], nets["bench"] = nav_b, net_b

    n_days = n_rb * HOLD
    q5_total = float(navs["q5"][-1] - 1.0)
    q1_total = float(navs["q1"][-1] - 1.0)
    b_total = float(navs["bench"][-1] - 1.0)
    out = {
        "q5_total": q5_total,
        "q5_annual": annualize(q5_total, n_days),
        "q5_sharpe": period_sharpe(nets["q5"]),
        "q5_maxdd": max_drawdown(navs["q5"]),
        "q1_total": q1_total,
        "q1_annual": annualize(q1_total, n_days),
        "bench_total": b_total,
        "bench_annual": annualize(b_total, n_days),
        "spread_annual": annualize(q5_total, n_days) - annualize(q1_total, n_days),
        "turnover": float(np.mean(q5_turnovers[1:])) if n_rb > 1 else 0.0,
        "n_rebalances": int(n_rb),
        "periods": int(n_days),
    }
    ic_mean, ic_ir = compute_ic(cast(pd.DataFrame, df[df["kline_time"].isin(cast(Any, use_dates))]))
    out["ic_mean"] = ic_mean
    out["ic_ir"] = ic_ir
    # internals for plotting (not in json)
    out["_navs"] = navs
    out["_rb_dates"] = [str(d.date()) for d in rb_dates]
    out["_q_annuals"] = {q: annualize(float(navs[f"q{q}"][-1] - 1.0), n_days) for q in range(1, 6)}
    return out


def plot_figs(res: dict, figdir: Path) -> None:
    figdir.mkdir(parents=True, exist_ok=True)
    navs = res["_navs"]
    x = np.arange(1, res["n_rebalances"] + 1)
    plt.figure(figsize=(9, 5))
    plt.plot(x, navs["q5"], label="Q5 long")
    plt.plot(x, navs["q1"], label="Q1 long")
    plt.plot(x, navs["bench"], label="Market EW bench")
    plt.xlabel("Rebalance index (5 trading days each)")
    plt.ylabel("NAV (start=1)")
    plt.title("Equity curves (net of fees)")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(figdir / "equity.png", dpi=120)
    plt.close()

    qs = [1, 2, 3, 4, 5]
    vals = [res["_q_annuals"][q] for q in qs]
    plt.figure(figsize=(7, 4.5))
    plt.bar([f"Q{q}" for q in qs], vals)
    plt.ylabel("Annualized return (net)")
    plt.title("Quintile annualized returns")
    plt.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(figdir / "quintile.png", dpi=120)
    plt.close()


def run_legacy_regression() -> None:
    """旧回归出口：C05 回归结论已归档为历史记录，本入口一律拒绝执行旧逻辑。"""
    from backtest.legacy import LegacyBacktestDisabledError, guard_legacy_disabled

    guard_legacy_disabled("backtest/engine:regression")
    raise LegacyBacktestDisabledError(
        "legacy regression is retired (see test_goal_adapter_regression.py C05 record); "
        "no opt-in re-run path"
    )


def run_adapter_default(args, out_dir: str) -> None:
    """默认路径：pred/market 双源 → goal_adapter 订单引擎 → backtest.json（adapter 口径）。"""
    from goal_adapter.runner import RUNNER_VERSION, run_goal_backtest

    outcome = run_goal_backtest(
        pred_path=args.pred, market_path=args.market, strategy=args.strategy,
        top_n=args.top_n, sell_buffer=args.sell_buffer, min_amount_yuan=args.min_amount,
        initial_capital=args.capital, model_name=args.model_name,
        model_artifact=args.model_artifact, feature_version=args.feature_version,
        script_version=args.script_version)
    metrics = {"engine": "goal_adapter", "strategy": args.strategy,
               "eval_script_version": RUNNER_VERSION, "top_n": outcome.provenance["top_n"],
               "final_nav": outcome.final_nav, "config_hash": outcome.config_hash,
               "data_fingerprint": outcome.data_fingerprint, **outcome.account_metrics}
    with open(Path(out_dir) / "backtest.json", "w") as f:
        json.dump(metrics, f, indent=2)
    with open(Path(out_dir) / "manifest.json", "w") as f:
        json.dump(outcome.manifest, f, indent=2)
    print(json.dumps({k: v for k, v in metrics.items() if k != "provenance"}, indent=2))


def run_legacy_quintile(args, out_dir: str) -> None:
    """旧 quintile 体（G01 起仅 opt-in 可达）：原 main() 逻辑逐行下沉，落盘加 legacy 标记。"""
    from backtest.legacy import guard_legacy_disabled, mark_legacy_result

    guard_legacy_disabled("backtest/engine:quintile")
    outdir = Path(out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(args.pred, columns=["code", "kline_time", "score", "future_ret_5d", "q_true"])
    res = run_backtest(df)
    plot_figs(res, outdir / "figs")
    public = mark_legacy_result({k: v for k, v in res.items() if not k.startswith("_")})
    with open(outdir / "backtest.json", "w") as f:
        json.dump(public, f, indent=2)
    print(json.dumps(public, indent=2))


def main(argv=None) -> None:
    args = parse_args(argv)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    if args.legacy:
        run_legacy_quintile(args, outdir.as_posix())
        return
    if not args.market:
        raise ValueError("默认 adapter 路径需要 --market 指定 train parquet；旧 quintile 体请走 --legacy")
    run_adapter_default(args, outdir.as_posix())


def parse_args(argv=None):
    from goal_adapter.runner import RUNNER_VERSION

    ap = argparse.ArgumentParser(description="goal 回测（默认 goal_adapter 订单引擎；旧 quintile 须 --legacy）")
    ap.add_argument("--pred", required=True)
    ap.add_argument("--market", default=None, help="adapter 默认路径必填：train_data parquet（真实 OHLC）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--strategy", choices=["daily", "joint"], default="daily")
    ap.add_argument("--top-n", dest="top_n", type=int, default=None, help="缺省取策略 C04 默认（daily 20/joint 100）")
    ap.add_argument("--sell-buffer", dest="sell_buffer", type=int, default=None)
    ap.add_argument("--min-amount", dest="min_amount", type=float, default=1e8)
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--legacy", action="store_true", help="显式 opt-in 旧 quintile 体（另需 GOAL_ALLOW_LEGACY=1）")
    ap.add_argument("--model-name", dest="model_name", default="goal-hgb")
    ap.add_argument("--model-artifact", dest="model_artifact", default="unknown")
    ap.add_argument("--feature-version", dest="feature_version", default="unknown")
    ap.add_argument("--script-version", dest="script_version", default=RUNNER_VERSION)
    return ap.parse_args(argv)


if __name__ == "__main__":
    main()
