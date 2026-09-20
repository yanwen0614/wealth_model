"""零售模型推理 + 预测缓存生成 (.npz: p_bin/ret_pred/true_ret/dates/codes)。

用法：
  uv run --project . python -m scripts.eval_retail_predict
    --checkpoint logs/run_retail_xxx/best_model.pth
    --infer_cfg logs/run_retail_xxx/inference_config.json
    --eval_start 2026-01-01 --eval_end 2026-08-31
    --preds_cache logs/retail_preds.npz
"""

import argparse
import glob
import json
import os
import random
from typing import cast

import numpy as np
import torch
from tqdm import tqdm

from config.defaults import DEFAULT_BINS
from data.dataset import ParquetDataConfig, ParquetDataset
from models.retail_friendly.config import RetailModelConfig
from models.retail_friendly.model import RetailFriendlyModel

EVAL_MODES = frozenset({"relative", "per_code", "rolling"})


def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_checkpoint(path: str | None) -> str:
    if path:
        return path
    cands = sorted(glob.glob("logs/run_retail_*/best_model.pth"))
    if not cands:
        raise FileNotFoundError("未找到 logs/run_retail_*/best_model.pth，请用 --checkpoint 指定")
    return cands[-1]


def load_run_config(ckpt_path: str) -> dict:
    cfg_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
    if not os.path.exists(cfg_path):
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    # 扁平化嵌套键
    flat = {}
    for k, v in cfg.items():
        if isinstance(v, dict):
            flat.update(v)
        else:
            flat[k] = v
    return flat


def load_infer_cfg(infer_cfg_path: str | None) -> dict:
    if infer_cfg_path and os.path.exists(infer_cfg_path):
        with open(infer_cfg_path) as f:
            return json.load(f)
    return {}


def parse_args():
    p = argparse.ArgumentParser(description="零售模型推理 + 预测缓存")
    p.add_argument("--checkpoint", type=str, default=None)
    p.add_argument("--infer_cfg", type=str, default=None)
    p.add_argument("--parquet", type=str, default=None)
    p.add_argument("--eval_start", type=str, default="2026-01-01")
    p.add_argument("--eval_end", type=str, default="2026-08-31")
    p.add_argument("--preds_cache", type=str, default="logs/retail_preds.npz")
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--normalize", type=str, default="relative",
                   choices=["per_code", "rolling", "relative"])
    p.add_argument("--rolling_scope", type=str, default="e5")
    p.add_argument("--max_codes", type=int, default=0, help="0=全量")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    args = parse_args()
    set_seed(args.seed)

    # 加载 checkpoint
    ckpt_path = resolve_checkpoint(args.checkpoint)
    run_cfg = load_run_config(ckpt_path)
    infer_cfg = load_infer_cfg(args.infer_cfg)

    # 从 state_dict 自动推断维度
    device = "cuda" if torch.cuda.is_available() else "cpu"
    state = torch.load(ckpt_path, map_location=device, weights_only=True)
    d_model = state["fc_bin.0.weight"].shape[0]
    featurenum = state["multi_window_cnn.stem.0.weight"].shape[1]
    print(f"加载模型: {ckpt_path}")
    print(f"  输入 F={featurenum}, d_model={d_model}")

    # 尝试从 config.json 或 infer_cfg 获取阈值
    threshold = infer_cfg.get("threshold",
                 run_cfg.get("RETAIL_DEFAULT_THRESHOLD", 0.65))
    print(f"  校准阈值: {threshold:.3f}")

    # 初始化模型
    model_cfg = RetailModelConfig(
        featurenum=featurenum,
        d_model=d_model,
        dropout_rate=run_cfg.get("dropout_rate", 0.3),
    )
    model = RetailFriendlyModel(model_cfg).to(device)
    model.load_state_dict(state)
    model.eval()
    print(f"模型加载成功: 总参 {sum(p.numel() for p in model.parameters()):,}")

    # 数据集
    parquet_path = args.parquet or run_cfg.get("PARQUET_PATH",
                                               "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet")
    normalize = args.normalize
    scaler_path = run_cfg.get("SCALER_PATH", None)

    print(f"创建推理数据集: {args.eval_start} ~ {args.eval_end}")
    ds_cfg = ParquetDataConfig(
        parquet_path=parquet_path,
        seq_len=60,
        horizon=5,
        bins=DEFAULT_BINS,
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        normalize=normalize,
        rolling_scope=args.rolling_scope,
        feature_cols=None,
        scaler_path=scaler_path,
        max_codes=args.max_codes if args.max_codes > 0 else None,
        role="evaluation",
        cache_enabled=False,
    )
    loader, _, _ = ParquetDataset.create_dataloaders(
        ds_cfg,
        train_start=None,
        train_end=None,
        val_start=args.eval_start,
        val_end=args.eval_end,
        scaler_path=scaler_path,
    )
    ds = cast(ParquetDataset, loader.dataset)
    print(f"数据集样本数: {len(ds):,}")

    # 推理
    all_p_bin, all_ret_pred, all_true_ret = [], [], []
    all_dates, all_codes = [], []
    offset = 0

    print("推理中...")
    for xb, yb, y_ret in tqdm(loader, desc="Inference", total=len(loader)):
        n = xb.shape[0]
        with torch.no_grad():
            p_bin, ret_pred = model(xb.to(device))
        all_p_bin.append(p_bin.cpu().numpy())
        all_ret_pred.append(ret_pred.cpu().numpy())
        all_true_ret.append(y_ret.numpy() if y_ret is not None else np.full(n, np.nan))

        # 提取日期和股票代码（方法与 eval_bins_mapping.py 一致）
        for i in range(n):
            grp_idx, pos = ds.index[offset + i]
            g = ds.groups[grp_idx]
            # 标签所在日期 = pos + seq_len - 1
            label_pos = pos + ds.config.seq_len - 1
            dt = g["kline_time"][label_pos] if "kline_time" in g.dtype.names else g["kline_time"][label_pos]
            code = g["code"] if "code" in g.dtype.names else grp_idx
            all_dates.append(dt)
            all_codes.append(str(ds.groups[grp_idx]["code"]) if isinstance(ds.groups[grp_idx], np.void) else str(grp_idx))
        offset += n

    # 合并
    p_bin_all = np.concatenate(all_p_bin)
    ret_pred_all = np.concatenate(all_ret_pred)
    true_ret_all = np.concatenate(all_true_ret)
    dates_all = np.array(all_dates, dtype="datetime64[D]")
    codes_all = np.array(all_codes, dtype="U16")

    print(f"\n推理完成: {len(p_bin_all)} 样本")

    # 简单统计
    print(f"  p_bin:   mean={p_bin_all.mean():.4f}  >0.5={((p_bin_all>0.5).mean()):.2%}")
    print(f"  ret_pred: mean={ret_pred_all.mean():.6f}")
    pos_rate = (true_ret_all > 0).mean() if np.isfinite(true_ret_all).any() else float("nan")
    print(f"  true_ret>0: {pos_rate:.2%}" if np.isfinite(pos_rate) else "  true_ret: 无数据")

    # 使用校准阈值评估
    pred_pos = p_bin_all >= threshold
    tp = ((pred_pos) & (true_ret_all > 0)).sum()
    fp = ((pred_pos) & (true_ret_all <= 0)).sum()
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + (true_ret_all > 0).sum() - tp, 1)
    print(f"  阈值={threshold:.3f}: precision={precision:.2%}  recall={recall:.2%}  "
          f"选股率={(pred_pos.mean()):.2%}")

    # 保存
    out_path = args.preds_cache
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    np.savez_compressed(out_path,
                        p_bin=p_bin_all,
                        ret_pred=ret_pred_all,
                        true_ret=true_ret_all,
                        dates=dates_all,
                        codes=codes_all)
    print(f"\n预测缓存已保存: {out_path}")


if __name__ == "__main__":
    main()
