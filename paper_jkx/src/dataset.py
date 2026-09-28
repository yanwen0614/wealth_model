"""数据集:parquet → (image, label) 样本,标签与回测同口径 open-open."""
import numpy as np
import pandas as pd

from .imaging import render_plus

# 成图 v2 叠加特征:长均线进价格区,量比+macd 进振荡器条(缺列时填 NaN 留空)
EXTRA_COLS = ("ma_20", "ma_60", "volume_ratio_5d", "macd")


def _f64(g, name):
    if name in g.columns:
        return g[name].to_numpy(np.float64)
    return np.full(len(g), np.nan)


def build_samples(df, n_days=5, horizon=5, max_codes=None, end_date=None,
                  start_date=None, stride=1, seed=0):
    """返回 [(img, y, code, date, true_ret)].

    y=1{open[t+1+h]/open[t+1]-1>0},true_ret 为该 open-open 可交易收益;
    有 is_trading 列时仅用 True 行;date 为标签日 T 字符串.
    """
    if "is_trading" in df.columns:
        df = df[df["is_trading"]]
    if start_date is not None:
        df = df[df["kline_time"] >= start_date]
    if end_date is not None:
        df = df[df["kline_time"] <= end_date]
    codes = sorted(df["code"].unique())
    if max_codes is not None:
        rng = np.random.RandomState(seed)
        codes = sorted(rng.choice(codes, size=min(max_codes, len(codes)),
                                  replace=False).tolist())
    out = []
    for code in codes:
        g = df[df["code"] == code].sort_values("kline_time").reset_index(drop=True)
        if len(g) < n_days + 1 + horizon:
            continue
        o = g["open"].to_numpy(float)
        hh = g["high"].to_numpy(float)
        ll = g["low"].to_numpy(float)
        close = g["close"].to_numpy(float)
        vv = g["volume"].to_numpy(float)
        ma = pd.Series(close).rolling(n_days, min_periods=1).mean().to_numpy()
        ex = [_f64(g, c) for c in EXTRA_COLS]
        dates = g["kline_time"].to_numpy()
        for t in range(n_days - 1, len(g) - 1 - horizon, stride):
            s = t - n_days + 1
            b, e = o[t + 1], o[t + 1 + horizon]
            if not (np.isfinite(b) and np.isfinite(e)) or b <= 0:
                continue
            ret = float(e / b - 1)
            y = 1 if ret > 0 else 0
            img = render_plus(o[s:t + 1], hh[s:t + 1], ll[s:t + 1],
                              close[s:t + 1], vv[s:t + 1],
                              [ma[s:t + 1], ex[0][s:t + 1], ex[1][s:t + 1]],
                              ex[2][s:t + 1], ex[3][s:t + 1], n_days=n_days)
            out.append((img, y, code, str(dates[t]), ret))
    return out


def build_index(df, n_days=5, horizon=5, max_codes=None, end_date=None,
                start_date=None, stride=1, seed=0):
    """全量索引:逐 code 存 float32 数组 + 全局 (pos, t) 索引,不预渲染图片.

    返回 dict(store/y/rets/dates/idx/n_days):store[code] 为 [T,10]
    列序 open/high/low/close/vol/ma_n/ma_20/ma_60/vol_ratio/macd;
    idx 为 [N,2] 的 (code_pos, t);y/true_ret/dates 为 [N] 级标签.
    """
    if "is_trading" in df.columns:
        df = df[df["is_trading"]]
    if start_date is not None:
        df = df[df["kline_time"] >= start_date]
    if end_date is not None:
        df = df[df["kline_time"] <= end_date]
    codes = sorted(df["code"].unique())
    if max_codes is not None:
        rng = np.random.RandomState(seed)
        codes = sorted(rng.choice(codes, size=min(max_codes, len(codes)),
                                  replace=False).tolist())
        df = df[df["code"].isin(codes)]  # 一次掩码,避免逐 code 全表扫描
    df = df.sort_values(["code", "kline_time"]).reset_index(drop=True)
    store, cpos, idx, y, rets, dates, codes_out = {}, {}, [], [], [], [], []
    for code, g in df.groupby("code", sort=False):
        if len(g) < n_days + 1 + horizon:
            continue
        pos = len(codes_out)
        codes_out.append(code)
        o = g["open"].to_numpy(np.float64)
        close = g["close"].to_numpy(np.float64)
        man = pd.Series(close).rolling(n_days, min_periods=1).mean().to_numpy()
        arr = np.stack([o, g["high"].to_numpy(np.float64),
                        g["low"].to_numpy(np.float64), close,
                        g["volume"].to_numpy(np.float64), man,
                        _f64(g, "ma_20"), _f64(g, "ma_60"),
                        _f64(g, "volume_ratio_5d"), _f64(g, "macd"),
                        ], axis=1).astype(np.float32)
        store[code], cpos[code] = arr, pos
        ds = g["kline_time"].to_numpy()
        for t in range(n_days - 1, len(g) - 1 - horizon, stride):
            b, e = float(o[t + 1]), float(o[t + 1 + horizon])
            if not (np.isfinite(b) and np.isfinite(e)) or b <= 0:
                continue
            r = e / b - 1
            idx.append((pos, t))
            y.append(1 if r > 0 else 0)
            rets.append(r)
            dates.append(str(ds[t]))
    return {"store": store, "codes": codes_out, "idx": np.array(idx, dtype=np.int64),
            "y": np.array(y, dtype=np.int64),
            "rets": np.array(rets, dtype=np.float64),
            "dates": np.array(dates), "n_days": n_days}


class LazyImageDataset:
    """torch 延迟渲染数据集:__getitem__ 时才成图,全量训练/推理用.

    num_workers>0 时要求 render 函数可 pickle(本模块顶层函数满足).
    """

    def __init__(self, index):
        self.index = index

    def __len__(self):
        return len(self.index["idx"])

    def __getitem__(self, i):
        import torch

        pos, t = (int(x) for x in self.index["idx"][i])
        code = self.index["codes"][pos]
        n = self.index["n_days"]
        s = t - n + 1
        arr = self.index["store"][code][s:t + 1]
        img = render_plus(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4],
                          [arr[:, 5], arr[:, 6], arr[:, 7]], arr[:, 8], arr[:, 9],
                          n_days=n)
        return (torch.from_numpy(img).unsqueeze(0),
                torch.tensor(int(self.index["y"][i]), dtype=torch.long))
