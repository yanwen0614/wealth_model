"""52->11 零重训映射评估（T03 Step1，只读评估，不改训练链路）.

链路：best_model.pth(52类) -> 验证集推理 logits -> softmax ->
  exp_ret=(probs*centers52).sum(-1), centers52=linspace(-0.255,0.255,52) ->
  np.digitize(exp_ret, bins11), bins11 默认百分制
  [-15,-10,-6,-3,-1,1,3,6,10,15]（内部 /100 化为小数，与 exp_ret 同单位；
  可经 --bins11_pct 传入 T02 冻结 bins 覆盖） ->
  对比 52 原样：RankIC / 分位命中 / Top10%。

约束：不改 train.py 默认链路，不改 BINS/num_classes(52)；
  training/metrics.py 的 num_classes 默认 6 已过时，本脚本一律显式传参。

用法：
  uv run --project . python -m scripts.eval_bins_mapping --max_codes 20
  uv run --project . python -m scripts.eval_bins_mapping --checkpoint logs/run_xxx/best_model.pth
"""
from __future__ import annotations

import os
import sysimport argparse
import glob
import json
import random

import numpy as np
import torch
from torch.utils.data import DataLoader

from config import DEFAULT_BINS
from data.dataset import ParquetDataConfig, ParquetDataset
from data.schema import validate_prediction_cache_arrays
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from training.metrics import calculate_latter_half_metrics

CENTERS52 = np.linspace(-0.255, 0.255, 52)  # 52 类中心（小数单位）
DEFAULT_BINS11_PCT = [-15, -10, -6, -3, -1, 1, 3, 6, 10, 15]  # 百分制，内部/100
DEFAULT_BINS13_PCT = [-15, -10, -7, -4, -2, -0.5, 0.5, 2, 4, 7, 10, 15]  # 百分制，内部/100
DEFAULT_BINS52 = DEFAULT_BINS
NUM_CLASSES52 = 52


def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_checkpoint(path: str | None) -> str:
    if path:
        return path
    cands = sorted(glob.glob("logs/run_*/best_model.pth"))
    if not cands:
        raise FileNotFoundError("未找到 logs/run_*/best_model.pth，请用 --checkpoint 指定")
    return cands[-1]


def load_run_model_cfg(ckpt_path: str) -> dict:
    """优先读 checkpoint 同目录 config.json 的 CNNTransformerConfig；附 pure_reg 模式标志（旧 ckpt 缺键默认 False）。"""
    cfg_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            run_cfg = json.load(f)
        mc = run_cfg.get("CNNTransformerConfig") or {}
        if mc.get("num_classes", 52) != NUM_CLASSES52:
            raise ValueError(f"checkpoint 非 52 类模型：{mc.get('num_classes')}（本脚本只评估 52 类零重训映射）")
        mc["pure_reg"] = bool(run_cfg.get("PURE_REG", False))
        return mc
    return {"pure_reg": False}


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """无 scipy 依赖的 Spearman（rank 后 Pearson）。"""
    xr = np.argsort(np.argsort(x)).astype(np.float64)
    yr = np.argsort(np.argsort(y)).astype(np.float64)
    xr -= xr.mean()
    yr -= yr.mean()
    denom = np.sqrt((xr ** 2).sum() * (yr ** 2).sum())
    return float((xr * yr).sum() / denom) if denom > 0 else 0.0


def build_val_loader(args) -> tuple[DataLoader, ParquetDataset]:
    cfg = ParquetDataConfig(
        parquet_path=args.parquet,
        seq_len=args.seq_len,
        horizon=args.horizon,
        bins=list(DEFAULT_BINS52),
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        normalize="per_code",
        max_codes=(args.max_codes if args.max_codes > 0 else None),
        max_windows_per_code=args.max_windows_per_code,
        start_date=args.val_start,
        end_date=args.val_end,
    )
    scaler_stats = None
    if args.scaler_path and os.path.exists(args.scaler_path):
        from data.scaler import PerCodeGroupedScaler

        scaler_stats = PerCodeGroupedScaler.load(args.scaler_path)
        print(f"[eval] 复用训练 scaler: {args.scaler_path}")
    elif not args.allow_fit_scaler:
        raise FileNotFoundError(
            f"正式评估必须复用训练 scaler，但文件不存在: {args.scaler_path}；"
            "调试时显式传入 --allow_fit_scaler"
        )
    else:
        print("[eval] 调试模式：scaler 不存在，验证集将自行拟合")
    ds = ParquetDataset(cfg, scaler_stats=scaler_stats)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False,
                        num_workers=args.num_workers, pin_memory=False)
    return loader, ds


@torch.no_grad()
def evaluate(args) -> dict:
    set_seed(args.seed)
    ckpt_path = resolve_checkpoint(args.checkpoint)
    print(f"[eval] checkpoint: {ckpt_path}")
    mc = load_run_model_cfg(ckpt_path)
    pure_reg = bool(mc.get("pure_reg", False))
    featurenum = int(mc.get("featurenum", 45))
    model_cfg = ModelConfig(
        featurenum=featurenum, seq_len=args.seq_len, num_classes=NUM_CLASSES52,
        cnn_out_channels=int(mc.get("cnn_out_channels", 128)),
        cnn_kernel_sizes=list(mc.get("cnn_kernel_sizes", [1, 3, 5, 7, 10])),
        d_model=int(mc.get("d_model", 256)), nhead=int(mc.get("nhead", 8)),
        num_encoder_layers=int(mc.get("num_encoder_layers", 4)),
        dropout_rate=float(mc.get("dropout_rate", 0.3)),
    )
    device = args.device if args.device else ("cuda" if torch.cuda.is_available() else "cpu")
    model = CNNTransformer(model_cfg).to(device)
    model.load_state_dict(torch.load(ckpt_path, map_location=device), strict=True)
    model.eval()

    loader, ds = build_val_loader(args)
    if featurenum != ds.num_features:
        raise ValueError(f"特征数不一致：checkpoint={featurenum} vs 验证集={ds.num_features}")

    bins11 = np.array(args.bins11_pct if args.bins11_pct else DEFAULT_BINS11_PCT,
                      dtype=np.float64) / 100.0  # 化为小数单位
    bins13 = np.array(args.bins13_pct if args.bins13_pct else DEFAULT_BINS13_PCT,
                      dtype=np.float64) / 100.0
    all_probs, all_pred52, all_true52, all_true_ret = [], [], [], []
    all_ret_pred = []
    all_dates = []
    all_codes = []
    offset = 0
    for xb, yb, *_ in loader:  # dataset 现返 3 元 (x, y_cls, y_ret)，*_ 兼容双头
        n = xb.shape[0]
        out = model(xb.to(device))
        if not isinstance(out, tuple) or len(out) != 2:
            raise ValueError("checkpoint 模型必须返回唯一双头 schema: (logits, ret_pred)")
        logits, ret_pred = out
        all_ret_pred.append(ret_pred.cpu().numpy())
        probs = torch.softmax(logits, dim=1).cpu().numpy()
        all_probs.append(probs)
        all_pred52.append(probs.argmax(axis=1))
        all_true52.append(yb.numpy())
        # 按顺序对齐连续真值（shuffle=False，offset 与 dataset.index 对应）
        def _get_true_ret(i, base_offset=offset):
            lp = ds.index[base_offset + i][1] + ds.config.seq_len - 1
            g = ds.groups[ds.index[base_offset + i][0]]
            if args.y_ret_type == "open_close":
                bo = g["open"][lp + 1]
                sc = g["close"][lp + 1 + ds.config.horizon]
                return sc / bo - 1.0 if bo > 0 and not np.isnan(bo) and not np.isnan(sc) else np.nan
            return float(g["future_ret"][lp])
        tr = np.array([_get_true_ret(i) for i in range(n)])
        pairs = [ds.index[offset + i] for i in range(n)]
        dt = np.array([ds.groups[p[0]]["kline_time"][p[1] + ds.config.seq_len - 1] for p in pairs])
        all_codes.append(np.asarray([p[0] for p in pairs]))
        all_true_ret.append(tr)
        all_dates.append(dt)
        offset += n
    probs = np.concatenate(all_probs)
    pred52 = np.concatenate(all_pred52)
    true52 = np.concatenate(all_true52)
    true_ret = np.concatenate(all_true_ret)
    exp_ret = np.concatenate(all_ret_pred) if pure_reg else (probs * CENTERS52).sum(axis=1)
    pred11 = np.digitize(exp_ret, bins11).astype(int)  # 0..10
    true11 = np.digitize(true_ret, bins11).astype(int)
    pred13 = np.digitize(exp_ret, bins13).astype(int)  # 0..12
    true13 = np.digitize(true_ret, bins13).astype(int)

    # --- 52 原样指标 ---
    acc52 = float((pred52 == true52).mean())
    lh_p, lh_r = calculate_latter_half_metrics(torch.from_numpy(true52), torch.from_numpy(pred52),
                                                   num_classes=NUM_CLASSES52,
                                                   weight_type="equal")
    rank_ic = spearman(exp_ret, true_ret)
    # --- 11/13 映射指标 ---
    acc11 = float((pred11 == true11).mean())
    acc13 = float((pred13 == true13).mean())
    # 分位命中：exp_ret 五分位 vs true_ret 五分位一致率
    pq = np.quantile(exp_ret, [0.2, 0.4, 0.6, 0.8])
    tq = np.quantile(true_ret, [0.2, 0.4, 0.6, 0.8])
    quint_hit = float((np.digitize(exp_ret, pq) == np.digitize(true_ret, tq)).mean())
    # Top10%：预测 exp_ret 最高 10% 样本的平均真实收益 / 为正占比
    thr = np.quantile(exp_ret, 0.9)
    top_mask = exp_ret >= thr
    top10_mean = float(true_ret[top_mask].mean()) if top_mask.any() else 0.0
    top10_pos = float((true_ret[top_mask] > 0).mean()) if top_mask.any() else 0.0
    bot_mask = exp_ret <= np.quantile(exp_ret, 0.1)
    spread = float(top10_mean - (true_ret[bot_mask].mean() if bot_mask.any() else 0.0))

    dates = np.concatenate(all_dates)
    uniq_dates = np.unique(dates)
    daily_ics, daily_spreads, xs_sizes = [], [], []
    t05_m, t05_p, t1_m, t1_p, t5_m, t5_p, t10_m, t10_p = [], [], [], [], [], [], [], []
    tn5_m, tn5_p, tn10_m, tn10_p, tn15_m, tn15_p, tn20_m, tn20_p = [], [], [], [], [], [], [], []
    for d in uniq_dates:
        m = dates == d
        nsz = int(m.sum())
        if nsz < 100:
            continue
        e, r = exp_ret[m], true_ret[m]
        daily_ics.append(spearman(e, r))
        xs_sizes.append(nsz)
        for k, lm, lp in ((0.005, t05_m, t05_p), (0.01, t1_m, t1_p), (0.05, t5_m, t5_p), (0.10, t10_m, t10_p)):
            top = r[e >= np.quantile(e, 1 - k)]
            lm.append(float(top.mean()) if top.size else 0.0)
            lp.append(float((top > 0).mean()) if top.size else 0.0)
        order = np.argsort(-e)
        for nn, lnm, lnp in ((5, tn5_m, tn5_p), (10, tn10_m, tn10_p), (15, tn15_m, tn15_p), (20, tn20_m, tn20_p)):
            topn = r[order[:nn]]
            lnm.append(float(topn.mean()) if topn.size else 0.0)
            lnp.append(float((topn > 0).mean()) if topn.size else 0.0)
        bot10 = r[e <= np.quantile(e, 0.1)]
        bm = float(bot10.mean()) if bot10.size else 0.0
        daily_spreads.append(t10_m[-1] - bm)
    xs_ok = bool(daily_ics)
    avg_sz = int(np.mean(xs_sizes)) if xs_ok else 0
    xs = {
        "xs_ndays": len(daily_ics),
        "xs_avg_size": avg_sz,
        "xs_rank_ic_mean": float(np.mean(daily_ics)) if xs_ok else 0.0,
        "xs_rank_ic_median": float(np.median(daily_ics)) if xs_ok else 0.0,
        "xs_rank_ic_pos_rate": float(np.mean(np.array(daily_ics) > 0)) if xs_ok else 0.0,
        "xs_top05_mean": float(np.mean(t05_m)) if xs_ok else 0.0,
        "xs_top05_pos_rate": float(np.mean(t05_p)) if xs_ok else 0.0,
        "xs_top1_mean": float(np.mean(t1_m)) if xs_ok else 0.0,
        "xs_top1_pos_rate": float(np.mean(t1_p)) if xs_ok else 0.0,
        "xs_top5_mean": float(np.mean(t5_m)) if xs_ok else 0.0,
        "xs_top5_pos_rate": float(np.mean(t5_p)) if xs_ok else 0.0,
        "xs_top10_mean": float(np.mean(t10_m)) if xs_ok else 0.0,
        "xs_top10_pos_rate": float(np.mean(t10_p)) if xs_ok else 0.0,
        "xs_spread_mean": float(np.mean(daily_spreads)) if xs_ok else 0.0,
        "xs_spread_median": float(np.median(daily_spreads)) if xs_ok else 0.0,
        "xs_spread_pos_rate": float(np.mean(np.array(daily_spreads) > 0)) if xs_ok else 0.0,
        "xs_top1_daily_picks": max(1, int(avg_sz * 0.01)) if xs_ok else 0,
        "xs_top05_daily_picks": max(1, int(avg_sz * 0.005)) if xs_ok else 0,
        "xs_topn5_mean": float(np.mean(tn5_m)) if xs_ok else 0.0,
        "xs_topn5_pos_rate": float(np.mean(tn5_p)) if xs_ok else 0.0,
        "xs_topn10_mean": float(np.mean(tn10_m)) if xs_ok else 0.0,
        "xs_topn10_pos_rate": float(np.mean(tn10_p)) if xs_ok else 0.0,
        "xs_topn15_mean": float(np.mean(tn15_m)) if xs_ok else 0.0,
        "xs_topn15_pos_rate": float(np.mean(tn15_p)) if xs_ok else 0.0,
        "xs_topn20_mean": float(np.mean(tn20_m)) if xs_ok else 0.0,
        "xs_topn20_pos_rate": float(np.mean(tn20_p)) if xs_ok else 0.0,
    }

    report = {
        "checkpoint": ckpt_path, "n": len(true52), "pure_reg": pure_reg,
        "bins11_pct": list(args.bins11_pct or DEFAULT_BINS11_PCT),
        "bins13_pct": list(args.bins13_pct or DEFAULT_BINS13_PCT),
        "acc52": acc52, "latter_half_precision52": lh_p, "latter_half_recall52": lh_r,
        "rank_ic_exp_vs_true": rank_ic, "quintile_hit": quint_hit,
        "acc11_mapped": acc11, "acc13_mapped": acc13, "top10_mean_true_ret": top10_mean,
        "top10_pos_rate": top10_pos, "top10_bottom10_spread": spread,
        **xs,
    }
    print("=" * 60)
    if pure_reg:
        print("[eval] pure_reg 模式：exp_ret=ret_pred，分类头未训练（52acc 仅供参考）")
    print(f"[eval] n={report['n']} bins11(百分制)={report['bins11_pct']}")
    print(f"[eval] bins13(百分制)={report['bins13_pct']}")
    print(f"  52原样: acc={acc52:.4f} 后半P={lh_p:.4f} R={lh_r:.4f} RankIC={rank_ic:.4f}")
    print(f"  11映射: acc={acc11:.4f} 五分位命中={quint_hit:.4f}")
    print(f"  13映射: acc={acc13:.4f} 五分位命中={quint_hit:.4f}")
    print(f"  Top10%: mean_true_ret={top10_mean:.4f} 为正率={top10_pos:.4f} 多空spread={spread:.4f}")
    print("=== 日截面指标 (per-date, 跳过截面<100样本) ===")
    if xs["xs_ndays"]:
        print(f"  截面数: {xs['xs_ndays']} 天 (日均样本 ~{xs['xs_avg_size']})")
        print(f"  截面RankIC: mean={xs['xs_rank_ic_mean']:.4f}"
              f" median={xs['xs_rank_ic_median']:.4f} >0天占比={xs['xs_rank_ic_pos_rate']:.4f}")
        print(f"  Top0.5%: mean_true_ret={xs['xs_top05_mean']:.4f} 为正率={xs['xs_top05_pos_rate']:.4f}"
              f" (日均选股 ~{xs['xs_top05_daily_picks']} 只)")
        print(f"  Top1%:  mean_true_ret={xs['xs_top1_mean']:.4f} 为正率={xs['xs_top1_pos_rate']:.4f}"
              f" (日均选股 ~{xs['xs_top1_daily_picks']} 只)")
        print(f"  Top5%:  mean_true_ret={xs['xs_top5_mean']:.4f} 为正率={xs['xs_top5_pos_rate']:.4f}")
        print(f"  Top10%: mean_true_ret={xs['xs_top10_mean']:.4f} 为正率={xs['xs_top10_pos_rate']:.4f}")
        print(f"  Top5只:  mean_true_ret={xs['xs_topn5_mean']:.4f} 为正率={xs['xs_topn5_pos_rate']:.4f}")
        print(f"  Top10只: mean_true_ret={xs['xs_topn10_mean']:.4f} 为正率={xs['xs_topn10_pos_rate']:.4f}")
        print(f"  Top15只: mean_true_ret={xs['xs_topn15_mean']:.4f} 为正率={xs['xs_topn15_pos_rate']:.4f}")
        print(f"  Top20只: mean_true_ret={xs['xs_topn20_mean']:.4f} 为正率={xs['xs_topn20_pos_rate']:.4f}")
        print(f"  多空spread(Top10%-Bot10%): mean={xs['xs_spread_mean']:.4f}"
              f" median={xs['xs_spread_median']:.4f} >0天占比={xs['xs_spread_pos_rate']:.4f}")
    else:
        print("  (无有效截面, 全部日期样本数<100)")
    print("=" * 60)
    if args.preds_cache:
        cache = {
            "exp_ret": exp_ret,
            "true_ret": true_ret,
            "dates": dates,
            "codes": np.concatenate(all_codes) if all_codes else np.asarray([], dtype="U1"),
        }
        validate_prediction_cache_arrays(cache, args.preds_cache)
        np.savez(args.preds_cache, **cache)
        print(f"[eval] 逐样本预测已缓存: {args.preds_cache} (exp_ret/true_ret/dates/codes, 后续统计免推理)")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"[eval] 报告已保存: {args.out}")
    return report


def parse_args():
    p = argparse.ArgumentParser(description="52->11 零重训映射评估")
    p.add_argument("--checkpoint", default=None, help="best_model.pth，默认最新 logs/run_*/best_model.pth")
    p.add_argument("--parquet", default="Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet")
    p.add_argument("--val_start", default="2025-07-01")
    p.add_argument("--val_end", default="2025-12-31")
    p.add_argument("--seq_len", type=int, default=60)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--preds_cache", default=None, help="逐样本预测缓存 npz 路径 (exp_ret/true_ret/dates/codes，codes 为逐样本股票代码)")
    p.add_argument("--max_codes", type=int, default=20)
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--scaler_path", default="logs/scaler_per_code.pkl")
    p.add_argument("--allow_fit_scaler", action="store_true",
                   help="仅调试：允许 scaler 缺失时在验证集自行拟合")
    p.add_argument("--bins11_pct", type=float, nargs="+", default=None, help="T02 冻结 bins（百分制），默认 [-15..15]")
    p.add_argument("--bins13_pct", type=float, nargs="+", default=None, help="13 映射 bins（百分制），默认 [-15..15]")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--y_ret_type", default="open_open", choices=["open_open", "open_close"])
    return p.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
