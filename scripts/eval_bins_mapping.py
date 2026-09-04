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
  uv run --project . python scripts/eval_bins_mapping.py --max_codes 20
  uv run --project . python scripts/eval_bins_mapping.py --checkpoint logs/run_xxx/best_model.pth
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import glob
import json
import random

import numpy as np
import torch
from torch.utils.data import DataLoader

from data.dataset import ParquetDataConfig, ParquetDataset
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from training.metrics import calculate_latter_half_metrics

CENTERS52 = np.linspace(-0.255, 0.255, 52)  # 52 类中心（小数单位）
DEFAULT_BINS11_PCT = [-15, -10, -6, -3, -1, 1, 3, 6, 10, 15]  # 百分制，内部/100
DEFAULT_BINS52 = (np.linspace(-25, 25, 51) / 100).tolist()  # 与 train.py DEFAULT_BINS 一致
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
    """优先读 checkpoint 同目录 config.json 的 CNNTransformerConfig。"""
    cfg_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            run_cfg = json.load(f)
        mc = run_cfg.get("CNNTransformerConfig") or {}
        if mc.get("num_classes", 52) != NUM_CLASSES52:
            raise ValueError(f"checkpoint 非 52 类模型：{mc.get('num_classes')}（本脚本只评估 52 类零重训映射）")
        return mc
    return {}


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
        max_codes=args.max_codes,
        max_windows_per_code=args.max_windows_per_code,
        start_date=args.val_start,
        end_date=args.val_end,
    )
    scaler_stats = None
    if args.scaler_path and os.path.exists(args.scaler_path):
        from data.scaler import PerCodeGroupedScaler

        scaler_stats = PerCodeGroupedScaler.load(args.scaler_path)
        print(f"[eval] 复用训练 scaler: {args.scaler_path}")
    else:
        print("[eval] 警告：scaler 不存在，验证集将自行拟合（仅调试可用，正式评估必须复用训练 scaler）")
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
    model.load_state_dict(torch.load(ckpt_path, map_location=device))
    model.eval()

    loader, ds = build_val_loader(args)
    if featurenum != ds.num_features:
        raise ValueError(f"特征数不一致：checkpoint={featurenum} vs 验证集={ds.num_features}")

    bins11 = np.array(args.bins11_pct if args.bins11_pct else DEFAULT_BINS11_PCT,
                      dtype=np.float64) / 100.0  # 化为小数单位
    all_probs, all_pred52, all_true52, all_true_ret = [], [], [], []
    offset = 0
    for xb, yb in loader:
        n = xb.shape[0]
        logits = model(xb.to(device))
        probs = torch.softmax(logits, dim=1).cpu().numpy()
        all_probs.append(probs)
        all_pred52.append(probs.argmax(axis=1))
        all_true52.append(yb.numpy())
        # 按顺序对齐连续真值（shuffle=False，offset 与 dataset.index 对应）
        tr = np.array([float(ds.groups[ds.index[offset + i][0]]["future_ret"][
            ds.index[offset + i][1] + ds.config.seq_len - 1]) for i in range(n)])
        all_true_ret.append(tr)
        offset += n
    probs = np.concatenate(all_probs)
    pred52 = np.concatenate(all_pred52)
    true52 = np.concatenate(all_true52)
    true_ret = np.concatenate(all_true_ret)
    exp_ret = (probs * CENTERS52).sum(axis=1)
    pred11 = np.digitize(exp_ret, bins11).astype(int)  # 0..10
    true11 = np.digitize(true_ret, bins11).astype(int)

    # --- 52 原样指标 ---
    acc52 = float((pred52 == true52).mean())
    lh_p, lh_r = calculate_latter_half_metrics(torch.from_numpy(true52), torch.from_numpy(pred52),
                                                   num_classes=NUM_CLASSES52,
                                                   weight_type="equal")
    rank_ic = spearman(exp_ret, true_ret)
    # --- 11 映射指标 ---
    acc11 = float((pred11 == true11).mean())
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

    report = {
        "checkpoint": ckpt_path, "n": len(true52),
        "bins11_pct": list(args.bins11_pct or DEFAULT_BINS11_PCT),
        "acc52": acc52, "latter_half_precision52": lh_p, "latter_half_recall52": lh_r,
        "rank_ic_exp_vs_true": rank_ic, "quintile_hit": quint_hit,
        "acc11_mapped": acc11, "top10_mean_true_ret": top10_mean,
        "top10_pos_rate": top10_pos, "top10_bottom10_spread": spread,
    }
    print("=" * 60)
    print(f"[eval] n={report['n']} bins11(百分制)={report['bins11_pct']}")
    print(f"  52原样: acc={acc52:.4f} 后半P={lh_p:.4f} R={lh_r:.4f} RankIC={rank_ic:.4f}")
    print(f"  11映射: acc={acc11:.4f} 五分位命中={quint_hit:.4f}")
    print(f"  Top10%: mean_true_ret={top10_mean:.4f} 为正率={top10_pos:.4f} 多空spread={spread:.4f}")
    print("=" * 60)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"[eval] 报告已保存: {args.out}")
    return report


def parse_args():
    p = argparse.ArgumentParser(description="52->11 零重训映射评估")
    p.add_argument("--checkpoint", default=None, help="best_model.pth，默认最新 logs/run_*/best_model.pth")
    p.add_argument("--parquet", default="data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet")
    p.add_argument("--val_start", default="2025-07-01")
    p.add_argument("--val_end", default="2025-12-31")
    p.add_argument("--seq_len", type=int, default=60)
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--max_codes", type=int, default=20)
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--scaler_path", default="logs/scaler_per_code.pkl")
    p.add_argument("--bins11_pct", type=float, nargs="+", default=None, help="T02 冻结 bins（百分制），默认 [-15..15]")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--device", default=None)
    p.add_argument("--out", default=None)
    return p.parse_args()


if __name__ == "__main__":
    evaluate(parse_args())
