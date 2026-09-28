"""适配器:推理概率 → preds npz → 复用现有回测链路,不自写会计.

复用:`backtest.engine.run_backtest_target/nav_metrics`(会计核心),
`scripts.build_ohlc_path.build_ohlc_full`(矩阵),
`scripts.run_backtest --mode target`(CLI 报告).本模块仅做格式转换.
"""
import numpy as np
import torch
from torch.utils.data import DataLoader

from backtest.engine import nav_metrics, run_backtest_target
from data.schema import validate_prediction_cache_arrays

from .models import ImageCNN
from .train import ImgDS


def predict_probs(ckpt, n_days, samples, bs=512):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = ImageCNN(n_days)
    model.load_state_dict(torch.load(ckpt, map_location="cpu"))
    model.to(dev).eval()
    probs = []
    with torch.no_grad():
        for xb, _ in DataLoader(ImgDS(samples), batch_size=bs, num_workers=0):
            probs.append(torch.softmax(model(xb.to(dev)), 1)[:, 1].cpu().numpy())
    return np.concatenate(probs)


def predict_index(ckpt, n_days, dataset, bs=2048, num_workers=4):
    """延迟索引批量推理,全量评估用;返回 [N] 上涨概率."""
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = ImageCNN(n_days)
    model.load_state_dict(torch.load(ckpt, map_location="cpu"))
    model.to(dev).eval()
    pin = dev == "cuda"
    probs = []
    with torch.no_grad():
        for xb, _ in DataLoader(dataset, batch_size=bs, num_workers=num_workers,
                                pin_memory=pin):
            probs.append(torch.softmax(model(xb.to(dev)), 1)[:, 1].cpu().numpy())
    return np.concatenate(probs)


def dump_index_cache(index, probs, path):
    """全量索引+概率 → preds npz,供现有回测 CLI 直接消费."""
    probs = np.asarray(probs, dtype=np.float64)
    codes = np.array(index["codes"])
    pos_of = np.array([p for p, _ in index["idx"]])
    cache = {"exp_ret": probs - 0.5,
             "true_ret": np.asarray(index["rets"], dtype=np.float64),
             "dates": np.asarray(index["dates"]).astype("datetime64[D]"),
             "codes": codes[pos_of]}
    validate_prediction_cache_arrays(cache, path)
    np.savez(path, **cache)
    return path


def dump_preds_cache(samples, probs, path):
    """样本+概率 → preds npz(exp_ret/true_ret/dates/codes),供现有回测 CLI 直接消费."""
    probs = np.asarray(probs, dtype=np.float64)
    exp_ret = probs - 0.5  # 保序即可,引擎按截面排序选股
    true_ret = np.array([s[4] if len(s) > 4 else float(s[1] * 2 - 1) for s in samples],
                        dtype=np.float64)
    codes = np.array([str(s[2]) for s in samples])
    dates = np.array([str(s[3]) for s in samples]).astype("datetime64[D]")
    cache = {"exp_ret": exp_ret, "true_ret": true_ret, "dates": dates, "codes": codes}
    validate_prediction_cache_arrays(cache, path)
    np.savez(path, **cache)
    return path


def run_existing_backtest(preds_path, full_ohlc, target_size=100, **kw):
    """复用引擎 target 模式回测,返回 {nav_metrics..., final_nav, n_closed_trades}."""
    z = np.load(preds_path, allow_pickle=False)
    res = run_backtest_target(z["exp_ret"].astype(np.float64),
                              np.asarray(z["codes"]), np.asarray(z["dates"]),
                              full_ohlc, target_size=target_size, **kw)
    m = nav_metrics(res.nav)
    return {**m, "final_nav": float(res.nav[-1]),
            "avg_cash_ratio": float(res.avg_cash_ratio),
            "n_closed_trades": len(res.holdings)}
