"""逐日回测会计核心（纯函数，numpy float64 in/out）.

口径：open-open（标签日 T 收盘选股 → T+1 open 买入 → T+6 open 卖出，跨 horizon=5 交易日），
双边成本 cost_rate 从每批收益一次性扣减；每日新批投入 = 当前净值/horizon，批内等权；
基准 = 全截面同口径等权（不筛涨停）。禁止前视：T 日净值只依赖 ≤T 信息。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

# OLD_LOGIC（阶段 3 N01）：旧 rolling/target 引擎路径标记，默认入口不再调用；
# 复用须经 backtest.legacy.guard_legacy_disabled 显式 opt-in。
OLD_LOGIC = True

import numpy as np

LIMIT_BASE = 1.098
LIMIT_20PCT = 1.198
LIMIT_20PCT_PREFIXES = ("300", "688")

_HOLDINGS_DTYPE = np.dtype([
    ("entry_date", "datetime64[D]"),
    ("exit_date", "datetime64[D]"),
    ("code", "U16"),
    ("weight", "f8"),
    ("open_t1", "f8"),
    ("open_t6", "f8"),
    ("ret_gross", "f8"),
    ("ret_net", "f8"),
])


class BacktestResult(NamedTuple):
    nav: np.ndarray
    holdings: np.ndarray
    skipped: dict


def _as_str(c) -> str:
    return c.decode("utf-8") if isinstance(c, bytes) else str(c)


def _norm_dates(d) -> np.ndarray:
    return np.asarray(d).astype("datetime64[D]")


def limit_up_mask(open_t1, t_close, codes) -> np.ndarray:
    open_t1 = np.asarray(open_t1, dtype=np.float64)
    t_close = np.asarray(t_close, dtype=np.float64)
    codes = np.asarray(codes)
    thr = np.full(open_t1.shape, LIMIT_BASE, dtype=np.float64)
    for i in range(len(codes)):
        if _as_str(codes[i])[:3] in LIMIT_20PCT_PREFIXES:
            thr[i] = LIMIT_20PCT
    return open_t1 >= t_close * thr


def _ohlc_lookup(ohlc: Mapping) -> dict:
    codes = np.asarray(ohlc["codes"])
    dates = _norm_dates(ohlc["dates"])
    lut = {}
    for i in range(len(codes)):
        lut[(_as_str(codes[i]), dates[i])] = i
    return lut


def _simulate(day_rets: list, n_days: int, horizon: int, cost_rate: float) -> np.ndarray:
    nav = np.ones(n_days, dtype=np.float64)
    pending: dict[int, float] = {}
    n_batch = max(int(horizon), 1)
    for i in range(n_days):
        if i > 0:
            nav[i] = nav[i - 1]
        nav[i] += pending.pop(i, 0.0)
        rets = day_rets[i]
        if not rets:
            continue
        end_i = i + 1 + horizon
        if end_i >= n_days:
            continue
        invest_each = nav[i] / n_batch / len(rets)
        gain = 0.0
        for g in rets:
            gain += invest_each * ((1.0 + g) * (1.0 - cost_rate) - 1.0)
        pending[end_i] = pending.get(end_i, 0.0) + gain
    return nav


def run_backtest(exp_ret, codes, dates, ohlc: Mapping, *, topn: int, cost_rate: float = 0.0015,
                 horizon: int = 5) -> BacktestResult:
    exp_ret = np.asarray(exp_ret, dtype=np.float64)
    codes_arr = np.asarray(codes)
    dates_n = _norm_dates(dates)
    if not (len(exp_ret) == len(codes_arr) == len(dates_n)):
        raise ValueError(f"exp_ret/codes/dates 长度不一致: {len(exp_ret)}/{len(codes_arr)}/{len(dates_n)}")
    if topn < 1:
        raise ValueError(f"topn 必须 >= 1, got {topn}")
    if horizon < 1:
        raise ValueError(f"horizon 必须 >= 1, got {horizon}")
    if not 0.0 <= cost_rate < 0.1:
        raise ValueError(f"cost_rate 应在 [0, 0.1), got {cost_rate}")

    lut = _ohlc_lookup(ohlc)
    t_close = np.asarray(ohlc["t_close"], dtype=np.float64)
    open_t1 = np.asarray(ohlc["open_t1"], dtype=np.float64)
    open_t6 = np.asarray(ohlc["open_t6"], dtype=np.float64)

    trade_days = np.unique(dates_n)
    n_days = len(trade_days)
    if n_days == 0:
        return BacktestResult(np.ones(1, dtype=np.float64), np.array([], dtype=_HOLDINGS_DTYPE), {})
    holdings: list = []
    skipped: dict = {}
    day_rets: list[list[float]] = [[] for _ in range(n_days)]

    for i, d in enumerate(trade_days):
        m = dates_n == d
        e = exp_ret[m]
        c = codes_arr[m]
        order = np.argsort(-e, kind="stable")[:topn]
        end_i = i + 1 + horizon
        picked: list = []
        skipped_n = 0
        for j in order:
            s = _as_str(c[j])
            row = lut.get((s, d))
            if row is None:
                continue
            o1, o6, tc = open_t1[row], open_t6[row], t_close[row]
            if np.isnan(o1) or np.isnan(o6) or np.isnan(tc):
                continue
            if o1 >= tc * (LIMIT_20PCT if s[:3] in LIMIT_20PCT_PREFIXES else LIMIT_BASE):
                skipped_n += 1
                continue
            if end_i >= n_days:
                continue
            gross = float(o6) / float(o1) - 1.0
            net = (1.0 + gross) * (1.0 - cost_rate) - 1.0
            picked.append((s, o1, o6, gross, net))
        if skipped_n:
            skipped[d] = skipped_n
        if picked and end_i < n_days:
            w = (1.0 / max(horizon, 1)) / len(picked)
            for s, o1, o6, g, nt in picked:
                holdings.append((d, trade_days[end_i], s, w, o1, o6, g, nt))
            day_rets[i] = [g for (_, _, _, g, _) in picked]

    holdings_arr = np.array(holdings, dtype=_HOLDINGS_DTYPE) if holdings else np.array([], dtype=_HOLDINGS_DTYPE)
    return BacktestResult(nav=_simulate(day_rets, n_days, horizon, cost_rate),
                          holdings=holdings_arr, skipped=skipped)


def benchmark_nav(codes, dates, ohlc: Mapping, *, cost_rate: float = 0.0015, horizon: int = 5) -> np.ndarray:
    codes_arr = np.asarray(codes)
    dates_n = _norm_dates(dates)
    if not (len(codes_arr) == len(dates_n)):
        raise ValueError(f"codes/dates 长度不一致: {len(codes_arr)}/{len(dates_n)}")

    lut = _ohlc_lookup(ohlc)
    open_t1 = np.asarray(ohlc["open_t1"], dtype=np.float64)
    open_t6 = np.asarray(ohlc["open_t6"], dtype=np.float64)

    trade_days = np.unique(dates_n)
    n_days = len(trade_days)
    if n_days == 0:
        return np.ones(1, dtype=np.float64)
    day_rets: list[list[float]] = [[] for _ in range(n_days)]

    for i, d in enumerate(trade_days):
        end_i = i + 1 + horizon
        if end_i >= n_days:
            continue
        for s_raw in codes_arr[dates_n == d]:
            s = _as_str(s_raw)
            row = lut.get((s, d))
            if row is None:
                continue
            o1, o6 = open_t1[row], open_t6[row]
            if np.isnan(o1) or np.isnan(o6):
                continue
            day_rets[i].append(float(o6) / float(o1) - 1.0)
    return _simulate(day_rets, n_days, horizon, cost_rate)


def nav_metrics(nav) -> dict:
    nav = np.asarray(nav, dtype=np.float64)
    if len(nav) < 2:
        return {"annual": 0.0, "sharpe": 0.0, "mdd": 0.0, "win_rate": 0.0}
    ret = nav[1:] / nav[:-1] - 1.0
    n = len(ret)
    std = ret.std()
    sharpe = float(ret.mean() / std * np.sqrt(252.0)) if std > 0 else 0.0
    peak = np.maximum.accumulate(nav)
    return {"annual": float(nav[-1] ** (252.0 / n) - 1.0), "sharpe": sharpe,
            "mdd": float((1.0 - nav / peak).max()), "win_rate": float((ret > 0).mean())}


def _close_holding(holdings: list, pos: dict, s: str, d, px: float, cost_rate: float) -> float:
    gross = px / pos[s]["entry_px"] - 1.0
    net = (1.0 + gross) * (1.0 - cost_rate) / (1.0 + cost_rate) - 1.0
    holdings.append((pos[s]["entry_date"], d, s, pos[s]["weight"], pos[s]["entry_px"], px, gross, net))
    return pos[s]["shares"] * px * (1.0 - cost_rate)


def run_backtest_target(exp_ret, codes, dates, full_ohlc: Mapping, *, target_size: int = 100,
                        sell_buffer: int = 200, min_edge: float = 0.01, edge_tail_pct: float = 0.3,
                        cost_rate: float = 0.0015) -> BacktestResult:
    """目标持仓模式（滞后带 + min_edge 费用感知过滤），事件驱动持有，无固定到期.

    T 日截面决策、T+1 open 执行：买入带 rank<=target_size，卖出带 rank>target_size+sell_buffer，
    区间内持仓不动；min_edge 过滤（后 edge_tail_pct 名且 exp_ret<min_edge）命中的候选跳过、空槽留现金。
    股数为 float（非整手），每笔预算 = nav/target_size 等权；买入付 open*(1+cost)，卖出收 open*(1-cost)。
    nav = cash + Σ 股数×当日 open；数据尾部最后交易日强制按 open 平仓（计成本）。
    """
    exp_ret = np.asarray(exp_ret, dtype=np.float64)
    codes_arr = np.asarray(codes)
    dates_n = _norm_dates(dates)
    if not (len(exp_ret) == len(codes_arr) == len(dates_n)):
        raise ValueError(f"exp_ret/codes/dates 长度不一致: {len(exp_ret)}/{len(codes_arr)}/{len(dates_n)}")
    if target_size < 1:
        raise ValueError(f"target_size 必须 >= 1, got {target_size}")
    if sell_buffer < 0:
        raise ValueError(f"sell_buffer 必须 >= 0, got {sell_buffer}")
    if min_edge < 0:
        raise ValueError(f"min_edge 必须 >= 0, got {min_edge}")
    if not 0.0 <= edge_tail_pct <= 1.0:
        raise ValueError(f"edge_tail_pct 应在 [0, 1], got {edge_tail_pct}")
    if not 0.0 <= cost_rate < 0.1:
        raise ValueError(f"cost_rate 应在 [0, 0.1), got {cost_rate}")
    full_codes = np.asarray(full_ohlc["codes"])
    trade_days = _norm_dates(full_ohlc["dates"])
    n_days = len(trade_days)
    if n_days and not bool(np.all(trade_days[1:] > trade_days[:-1])):
        raise ValueError("full_ohlc dates 需为升序唯一交易日")
    if len(exp_ret) == 0 or n_days == 0:
        return BacktestResult(np.ones(max(n_days, 1), dtype=np.float64),
                              np.array([], dtype=_HOLDINGS_DTYPE), {})
    open_m = np.asarray(full_ohlc["open_m"], dtype=np.float64)
    close_m = np.asarray(full_ohlc["close_m"], dtype=np.float64)
    row_of = {_as_str(c): i for i, c in enumerate(full_codes)}
    holdings: list = []
    skipped: dict = {}
    pos: dict = {}
    cash = 1.0
    nav = np.ones(n_days, dtype=np.float64)
    prev_dec = None

    for i, d in enumerate(trade_days):
        for s, p in pos.items():
            px = open_m[row_of[s], i]
            if not np.isnan(px):
                p["price"] = px
        if i > 0 and prev_dec is not None:
            order_list, rank_map, exp_map = prev_dec
            for s in [s for s in pos if rank_map.get(s, 0) > target_size + sell_buffer]:
                px = open_m[row_of[s], i]
                if np.isnan(px):
                    px = pos[s]["price"]
                cash += _close_holding(holdings, pos, s, d, px, cost_rate)
                del pos[s]
            nav_pre = cash + sum(p["shares"] * p["price"] for p in pos.values())
            if i < n_days - 1 and nav_pre > 0:
                slots = target_size - len(pos)
                skips = {"limit_up": 0, "min_edge": 0}
                for k in range(min(target_size, len(order_list))):
                    if slots <= 0:
                        break
                    s = order_list[k]
                    if s in pos:
                        continue
                    if rank_map[s] / target_size > 1.0 - edge_tail_pct and exp_map[s] < min_edge:
                        skips["min_edge"] += 1
                        continue
                    row = row_of.get(s)
                    if row is None:
                        continue
                    px = open_m[row, i]
                    prev_close = close_m[row, i - 1]
                    if np.isnan(px) or np.isnan(prev_close):
                        continue
                    thr = LIMIT_20PCT if s[:3] in LIMIT_20PCT_PREFIXES else LIMIT_BASE
                    if px >= prev_close * thr:
                        skips["limit_up"] += 1
                        continue
                    budget = nav_pre / target_size
                    shares = budget / (px * (1.0 + cost_rate))
                    cash -= shares * px * (1.0 + cost_rate)
                    pos[s] = {"shares": shares, "price": px, "entry_date": d, "entry_px": px,
                              "weight": budget / nav_pre}
                    slots -= 1
                if skips["limit_up"] or skips["min_edge"]:
                    skipped[d] = {k: v for k, v in skips.items() if v}
        if i == n_days - 1 and pos:
            for s in list(pos):
                px = open_m[row_of[s], i]
                if np.isnan(px):
                    px = pos[s]["price"]
                cash += _close_holding(holdings, pos, s, d, px, cost_rate)
            pos = {}
        nav[i] = cash + sum(p["shares"] * p["price"] for p in pos.values())
        m = dates_n == d
        if m.any():
            e = exp_ret[m]
            order = np.argsort(-e, kind="stable")
            cs = codes_arr[m]
            order_list = [_as_str(cs[j]) for j in order]
            rank_map = {s: k + 1 for k, s in enumerate(order_list)}
            exp_map = {order_list[k]: float(e[order[k]]) for k in range(len(order_list))}
            prev_dec = (order_list, rank_map, exp_map)
    holdings_arr = np.array(holdings, dtype=_HOLDINGS_DTYPE) if holdings else np.array([], dtype=_HOLDINGS_DTYPE)
    return BacktestResult(nav=nav, holdings=holdings_arr, skipped=skipped)
