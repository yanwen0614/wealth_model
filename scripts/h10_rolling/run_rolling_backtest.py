# H10滚动回测：engine目标持仓跑100/200+MA40 regime过滤200f
# 输入：combined.npz预测+logs/ohlc_full_rolling.npz，须在仓库根目录运行
# 输出：results.npz(nav100/nav200/nav200f+holdings+cash+days)
# 已验证：s2原稿直跑通；s2b补丁200f改strong_buy=1e-12，已并入下文kw2
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backtest.engine import run_backtest_target

P = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_bt\combined.npz"
R = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_bt\results.npz"
OHLC = str(ROOT / "logs" / "ohlc_full_rolling.npz")


def main():
    z = np.load(P, allow_pickle=True)
    e = np.asarray(z["exp_ret"], float); c = np.asarray(z["codes"]).astype(str)
    d = z["dates"].astype("datetime64[D]")
    o = np.load(OHLC, allow_pickle=True)
    oc = np.asarray(o["codes"]).astype(str); od = o["dates"].astype("datetime64[D]")
    m = (od >= d.min()) & (od <= np.datetime64("2025-12-31"))
    od = od[m]; om = np.asarray(o["open_m"], float)[:, m]; cm = np.asarray(o["close_m"], float)[:, m]
    ohlc = {"codes": oc, "dates": od, "open_m": om, "close_m": cm}
    kw = dict(exit_on_nonpositive=True, exit_threshold=0.0, strong_buy_threshold=0.0)
    r100 = run_backtest_target(e, c, d, ohlc, target_size=100, **kw)
    r200 = run_backtest_target(e, c, d, ohlc, target_size=200, **kw)
    rt = np.where(np.isfinite(cm[:, 1:]), cm[:, 1:] / np.where(cm[:, :-1] == 0, np.nan, cm[:, :-1]) - 1, np.nan)
    mr = np.nanmean(rt, axis=0); mr = np.where(np.isfinite(mr), mr, 0.0)
    ix = np.cumprod(np.concatenate([[1.0], 1 + mr]))
    ma = np.concatenate([np.full(39, np.nan), np.convolve(ix, np.ones(40) / 40, "valid")])
    on = np.where(np.isnan(ma), True, ix > ma)
    off = set(od[~on].astype(str)); e2 = e.copy(); e2[np.isin(d.astype(str), list(off))] = -np.inf
    kw2 = dict(kw, strong_buy_threshold=1e-12)  # s2b_fix补丁：200f用1e-12重跑覆盖
    r200f = run_backtest_target(e2, c, d, ohlc, target_size=200, **kw2)
    np.savez_compressed(R, nav100=r100.nav, nav200=r200.nav, nav200f=r200f.nav,
        h100=r100.holdings, h200=r200.holdings, h200f=r200f.holdings, days=od,
        cash100=r100.avg_cash_ratio, cash200=r200.avg_cash_ratio, cash200f=r200f.avg_cash_ratio)
    print("days:", len(od), od.min(), od.max(), "regime_on:", round(float(on.mean()), 4), flush=True)
    print("cash:", round(r100.avg_cash_ratio, 4), round(r200.avg_cash_ratio, 4), round(r200f.avg_cash_ratio, 4), flush=True)


if __name__ == "__main__":
    main()
