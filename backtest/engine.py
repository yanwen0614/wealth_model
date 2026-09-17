"""逐日回测会计核心（纯函数，numpy float64 in/out）.

口径：open-open（标签日 T 收盘选股 → T+1 open 买入 → T+6 open 卖出，跨 horizon=5 交易日），
逐笔 A 股费用模型（买/卖佣金万2.5 最低 5 元 + 卖出印花税万2.5，本金 capital 折算最低佣金）；
每日新批投入 = 当前净值/horizon，批内等权；基准 = 全截面同口径等权（不筛涨停）。
禁止前视：T 日净值只依赖 ≤T 信息。
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

BUY_COMMISSION_RATE = 0.00025
SELL_COMMISSION_RATE = 0.00025
STAMP_DUTY_RATE = 0.00025
MIN_COMMISSION = 5.0
DEFAULT_CAPITAL = 1_000_000.0

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
    avg_cash_ratio: float = 0.0


def _as_str(c) -> str:
    return c.decode("utf-8") if isinstance(c, bytes) else str(c)


def _norm_dates(d) -> np.ndarray:
    return np.asarray(d).astype("datetime64[D]")


def commission(notional_yuan: float, rate: float, min_commission: float = MIN_COMMISSION) -> float:
    """单笔佣金（元）：成交额 × 费率，不足最低佣金时取下限."""
    return max(notional_yuan * rate, min_commission)


def net_return_after_fees(buy_notional: float, sell_notional: float, *,
                          buy_rate: float = BUY_COMMISSION_RATE, sell_rate: float = SELL_COMMISSION_RATE,
                          stamp_rate: float = STAMP_DUTY_RATE,
                          min_commission: float = MIN_COMMISSION) -> float:
    """单笔净收益 = (卖额 − 卖佣 − 印花税 − 买额 − 买佣) / (买额 + 买佣)."""
    buy_fee = commission(buy_notional, buy_rate, min_commission)
    sell_fee = commission(sell_notional, sell_rate, min_commission) + sell_notional * stamp_rate
    return (sell_notional - sell_fee - buy_notional - buy_fee) / (buy_notional + buy_fee)


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


def _validate_fee_inputs(capital, buy_rate, sell_rate, stamp_rate, min_commission) -> None:
    if capital <= 0:
        raise ValueError(f"capital 必须 > 0, got {capital}")
    for name, r in (("buy_rate", buy_rate), ("sell_rate", sell_rate), ("stamp_rate", stamp_rate)):
        if r < 0:
            raise ValueError(f"{name} 必须 >= 0, got {r}")
    if min_commission < 0:
        raise ValueError(f"min_commission 必须 >= 0, got {min_commission}")


def _simulate(day_rets: list, n_days: int, horizon: int, *, capital: float = DEFAULT_CAPITAL,
              buy_rate: float = BUY_COMMISSION_RATE, sell_rate: float = SELL_COMMISSION_RATE,
              stamp_rate: float = STAMP_DUTY_RATE, min_commission: float = MIN_COMMISSION) -> np.ndarray:
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
        buy_notional = invest_each * capital
        gain = 0.0
        for g in rets:
            gain += invest_each * net_return_after_fees(
                buy_notional, buy_notional * (1.0 + g), buy_rate=buy_rate, sell_rate=sell_rate,
                stamp_rate=stamp_rate, min_commission=min_commission)
        pending[end_i] = pending.get(end_i, 0.0) + gain
    return nav


def run_backtest(exp_ret, codes, dates, ohlc: Mapping, *, topn: int, horizon: int = 5,
                 capital: float = DEFAULT_CAPITAL, buy_rate: float = BUY_COMMISSION_RATE,
                 sell_rate: float = SELL_COMMISSION_RATE, stamp_rate: float = STAMP_DUTY_RATE,
                 min_commission: float = MIN_COMMISSION) -> BacktestResult:
    """滚动模式：每日按 nav/horizon 满仓滚动，无闲置现金，故 avg_cash_ratio 恒为 0.0."""
    exp_ret = np.asarray(exp_ret, dtype=np.float64)
    codes_arr = np.asarray(codes)
    dates_n = _norm_dates(dates)
    if not (len(exp_ret) == len(codes_arr) == len(dates_n)):
        raise ValueError(f"exp_ret/codes/dates 长度不一致: {len(exp_ret)}/{len(codes_arr)}/{len(dates_n)}")
    if topn < 1:
        raise ValueError(f"topn 必须 >= 1, got {topn}")
    if horizon < 1:
        raise ValueError(f"horizon 必须 >= 1, got {horizon}")
    _validate_fee_inputs(capital, buy_rate, sell_rate, stamp_rate, min_commission)

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
            picked.append((s, o1, o6, gross))
        if skipped_n:
            skipped[d] = skipped_n
        if picked and end_i < n_days:
            w = (1.0 / max(horizon, 1)) / len(picked)
            buy_notional = w * capital
            for s, o1, o6, g in picked:
                net = net_return_after_fees(buy_notional, buy_notional * (1.0 + g), buy_rate=buy_rate,
                                            sell_rate=sell_rate, stamp_rate=stamp_rate,
                                            min_commission=min_commission)
                holdings.append((d, trade_days[end_i], s, w, o1, o6, g, net))
            day_rets[i] = [g for (_, _, _, g) in picked]

    holdings_arr = np.array(holdings, dtype=_HOLDINGS_DTYPE) if holdings else np.array([], dtype=_HOLDINGS_DTYPE)
    return BacktestResult(nav=_simulate(day_rets, n_days, horizon, capital=capital, buy_rate=buy_rate,
                                        sell_rate=sell_rate, stamp_rate=stamp_rate,
                                        min_commission=min_commission),
                          holdings=holdings_arr, skipped=skipped, avg_cash_ratio=0.0)


def benchmark_nav(codes, dates, ohlc: Mapping, *, horizon: int = 5, capital: float = DEFAULT_CAPITAL,
                  buy_rate: float = BUY_COMMISSION_RATE, sell_rate: float = SELL_COMMISSION_RATE,
                  stamp_rate: float = STAMP_DUTY_RATE,
                  min_commission: float = MIN_COMMISSION) -> np.ndarray:
    codes_arr = np.asarray(codes)
    dates_n = _norm_dates(dates)
    if not (len(codes_arr) == len(dates_n)):
        raise ValueError(f"codes/dates 长度不一致: {len(codes_arr)}/{len(dates_n)}")
    _validate_fee_inputs(capital, buy_rate, sell_rate, stamp_rate, min_commission)

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
    return _simulate(day_rets, n_days, horizon, capital=capital, buy_rate=buy_rate,
                     sell_rate=sell_rate, stamp_rate=stamp_rate, min_commission=min_commission)


def benchmark_index_nav(index_dates, index_close, trade_days) -> np.ndarray:
    """大盘指数 close-to-close 基准 NAV（纯函数，无 IO）.

    取指数收盘价日收益、按 trade_days（datetime64[D]）对齐；起点 1.0，缺失日收益记 0
    （净值保持不变），指数不可直接交易故不计费率。返回长度 = len(trade_days)。
    """
    idates = _norm_dates(index_dates)
    iclose = np.asarray(index_close, dtype=np.float64)
    tdays = _norm_dates(trade_days)
    n = len(tdays)
    if n == 0:
        return np.ones(0, dtype=np.float64)
    if not (len(idates) == len(iclose)):
        raise ValueError(f"index_dates/index_close 长度不一致: {len(idates)}/{len(iclose)}")
    order = np.argsort(idates, kind="stable")
    close_by_date = {}
    for dt, px in zip(idates[order].tolist(), iclose[order].tolist()):
        if np.isfinite(px):
            close_by_date[dt] = px

    nav = np.ones(n, dtype=np.float64)
    last_close = None
    prev = 1.0
    for i, d in enumerate(tdays.tolist()):
        px = close_by_date.get(d)
        if px is not None and last_close is not None:
            prev = prev * (px / last_close)
        nav[i] = prev
        if px is not None:
            last_close = px
    return nav


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


def _close_holding(holdings: list, pos: dict, s: str, d, px: float, *, capital: float,
                   buy_rate: float, sell_rate: float, stamp_rate: float,
                   min_commission: float) -> float:
    """卖出持仓：写入 holdings（ret_net 以买入总成本为基数），返回折回 NAV 单位的净现金."""
    entry_notional = pos[s]["shares"] * pos[s]["entry_px"]
    entry_cost = entry_notional + commission(entry_notional, buy_rate, min_commission)
    sell_notional = pos[s]["shares"] * px
    sell_fee = commission(sell_notional, sell_rate, min_commission) + sell_notional * stamp_rate
    proceeds = sell_notional - sell_fee
    gross = px / pos[s]["entry_px"] - 1.0
    net = (proceeds - entry_cost) / entry_cost
    holdings.append((pos[s]["entry_date"], d, s, pos[s]["weight"], pos[s]["entry_px"], px, gross, net))
    return proceeds / capital


def run_backtest_target(exp_ret, codes, dates, full_ohlc: Mapping, *, target_size: int = 100,
                        sell_buffer: int = 500,
                        exit_on_nonpositive: bool = False, exit_threshold: float = 0.0,
                        strong_buy_threshold: float = 0.0,
                        capital: float = DEFAULT_CAPITAL, buy_rate: float = BUY_COMMISSION_RATE,
                        sell_rate: float = SELL_COMMISSION_RATE, stamp_rate: float = STAMP_DUTY_RATE,
                        min_commission: float = MIN_COMMISSION) -> BacktestResult:
    """目标持仓模式（滞后带 + strong_buy_threshold 费用感知过滤），事件驱动持有，无固定到期.

    T 日截面决策、T+1 open 执行：买入带 rank<=target_size；退出默认 rank>target_size+sell_buffer，
    或 exit_on_nonpositive 时改为 exp_ret<=exit_threshold（忽略 rank buffer，缺预测不卖）。
    strong_buy_threshold>0 时，买入带内 exp_ret<strong_buy_threshold 的候选跳过该槽、留现金、不补位
    （0.0 为关闭哨兵；门槛作用于买入带全部候选，执行顺序 strong_buy → 涨停检查）。
    股数为 float（非整手），每笔预算 = (nav/target_size)×capital 元；逐笔 A 股费用模型。
    nav = cash + Σ 股数×当日 open / capital；数据尾部最后交易日强制按 open 平仓（计费用）。
    avg_cash_ratio = 逐日 cash/nav[i]（nav[i]>0）的均值，用于观测平均闲置现金仓位。
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
    if strong_buy_threshold < 0:
        raise ValueError(f"strong_buy_threshold 必须 >= 0, got {strong_buy_threshold}")
    _validate_fee_inputs(capital, buy_rate, sell_rate, stamp_rate, min_commission)
    full_codes = np.asarray(full_ohlc["codes"])
    trade_days = _norm_dates(full_ohlc["dates"])
    n_days = len(trade_days)
    if n_days and not bool(np.all(trade_days[1:] > trade_days[:-1])):
        raise ValueError("full_ohlc dates 需为升序唯一交易日")
    if len(exp_ret) == 0 or n_days == 0:
        return BacktestResult(np.ones(max(n_days, 1), dtype=np.float64),
                              np.array([], dtype=_HOLDINGS_DTYPE), {}, avg_cash_ratio=1.0)
    open_m = np.asarray(full_ohlc["open_m"], dtype=np.float64)
    close_m = np.asarray(full_ohlc["close_m"], dtype=np.float64)
    row_of = {_as_str(c): i for i, c in enumerate(full_codes)}
    holdings: list = []
    skipped: dict = {}
    pos: dict = {}
    cash = 1.0
    nav = np.ones(n_days, dtype=np.float64)
    cash_ratios: list[float] = []
    prev_dec = None

    for i, d in enumerate(trade_days):
        for s, p in pos.items():
            px = open_m[row_of[s], i]
            if not np.isnan(px):
                p["price"] = px
        if i > 0 and prev_dec is not None:
            order_list, rank_map, exp_map = prev_dec
            if exit_on_nonpositive:
                to_sell = [s for s in pos if exp_map.get(s) is not None and exp_map[s] <= exit_threshold]
            else:
                to_sell = [s for s in pos if rank_map.get(s, 0) > target_size + sell_buffer]
            for s in to_sell:
                px = open_m[row_of[s], i]
                if np.isnan(px):
                    px = pos[s]["price"]
                cash += _close_holding(holdings, pos, s, d, px, capital=capital, buy_rate=buy_rate,
                                       sell_rate=sell_rate, stamp_rate=stamp_rate,
                                       min_commission=min_commission)
                del pos[s]
            nav_pre = cash + sum(p["shares"] * p["price"] for p in pos.values()) / capital
            if i < n_days - 1 and nav_pre > 0:
                slots = target_size - len(pos)
                skips = {"limit_up": 0, "strong_buy": 0}
                for k in range(min(target_size, len(order_list))):
                    if slots <= 0:
                        break
                    s = order_list[k]
                    if s in pos:
                        continue
                    if strong_buy_threshold > 0.0 and exp_map[s] < strong_buy_threshold:
                        skips["strong_buy"] += 1
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
                    budget = (nav_pre / target_size) * capital
                    if budget <= min_commission:
                        continue
                    b_star = (min_commission * (1.0 + buy_rate) / buy_rate) if buy_rate > 0 else float("inf")
                    if budget >= b_star:
                        shares = budget / (px * (1.0 + buy_rate))
                    else:
                        shares = (budget - min_commission) / px
                    buy_notional = shares * px
                    buy_fee = commission(buy_notional, buy_rate, min_commission)
                    cash -= (buy_notional + buy_fee) / capital
                    pos[s] = {"shares": shares, "price": px, "entry_date": d, "entry_px": px,
                              "weight": 1.0 / target_size}
                    slots -= 1
                if skips["limit_up"] or skips["strong_buy"]:
                    skipped[d] = {k: v for k, v in skips.items() if v}
        if i == n_days - 1 and pos:
            for s in list(pos):
                px = open_m[row_of[s], i]
                if np.isnan(px):
                    px = pos[s]["price"]
                cash += _close_holding(holdings, pos, s, d, px, capital=capital, buy_rate=buy_rate,
                                       sell_rate=sell_rate, stamp_rate=stamp_rate,
                                       min_commission=min_commission)
            pos = {}
        nav[i] = cash + sum(p["shares"] * p["price"] for p in pos.values()) / capital
        if nav[i] > 0:
            cash_ratios.append(cash / nav[i])
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
    avg_cash = float(np.mean(cash_ratios)) if cash_ratios else 0.0
    return BacktestResult(nav=nav, holdings=holdings_arr, skipped=skipped, avg_cash_ratio=avg_cash)
