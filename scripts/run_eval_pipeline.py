"""全流程评估脚本：scaler → 推理缓存 → OHLC 路径表 —步到位。

渐进式接口：先 run 不指定 --checkpoint 查看默认跑什么，再显式传参精确控制。

scaler 解析优先级（T04，与 eval_bins_mapping.load_eval_preprocessing 一致）：
  ① checkpoint 同目录 config.json 的 preprocessing.state_path/scaler_path/SCALER_PATH
    （+顶层 SCALER_PATH，以此为准）；② 无元数据时 rolling 默认
     logs/rolling_e4/scaler_rolling_e4.pkl（旧 logs/rolling/ 路径已废弃）；
  ③ per_code 沿用既有默认 logs/scaler_per_code.pkl。异 scope
  （state scope != 请求 scope）直接抛错，不静默复用。

五项取数说明（给定 run_dir / preds 缓存即可输出，不重跑训练）：
  1. IC/ICIR：eval_bins_mapping 报告 rank_ic_exp_vs_true + xs_rank_ic_*（日截面 RankIC 均值/中位数/>0占比）。
  2. top-bottom：top10_bottom10_spread + xs_spread_*（Top10%-Bot10% 多空 spread）。
  3. 换手成本后收益：scripts/run_backtest.py --cost_rate 0.0015（默认双边一次性扣减）→ metrics.json
     各 topn annual/sharpe/mdd + excess_annual（相对全截面等权基准）。
  4. fallback 比例：<run_log_dir>/config.json -> preprocessing.rolling_audit（fallback_ratio/
     fallback_values/rolling_values；仅 rolling 有，per_code 无此键）。
  5. winsor 统计：同一 rolling_audit（constant_iqr_values/missing_values/neutral_fallback_values）。
回测口径（引用 backtest/engine.py，不重实现）：T 日决策→T+1 open 买入→T+6 open 卖出
  （horizon=5，open-open 口径，详见 backtest/engine.py 模块 docstring 与 run_backtest.py NOTE）。

E1–E4 评估命令（checkpoint 路径已按 scope 隔离，位置参数直接透传）：
  bash scripts/run_eval_full.sh logs/rolling_e2/<run>/best_model.pth 2026-01-01 2026-08-31
  bash scripts/run_eval_full.sh logs/rolling_e3/<run>/best_model.pth 2026-01-01 2026-08-31
  bash scripts/run_eval_full.sh logs/rolling_e4/<run>/best_model.pth 2026-01-01 2026-08-31
  rolling_audit 取数：jq .preprocessing.rolling_audit <run_log_dir>/config.json
  preds 缓存须含 exp_ret/true_ret/dates/codes；缺 codes 用 eval_bins_mapping 重建。

用法：
  # 默认：最新 checkpoint + 2026 验证 + 全市场
  uv run --project . python -m scripts.run_eval_pipeline

  # 指定 checkpoint 和时间范围
  uv run --project . python -m scripts.run_eval_pipeline \
    --checkpoint logs/run_20260905_010942/best_model.pth \
    --parquet data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet \
    --start 2026-01-01 --end 2026-08-31 \
    --batch_size 512 --num_workers 0

  # 仅生成 ohlc（跳过推理，适用于已有 preds_cache）
  uv run --project . python -m scripts.run_eval_pipeline --ohlc-only

  # 仅推理（跳过 build_ohlc_path，适用于已有 ohlc npz）
  uv run --project . python -m scripts.run_eval_pipeline --preds-only

输出（均到 logs/）：
  scaler_per_code.pkl         (如不存在时由训练集拟合)
  preds_<checkpoint_stem>_<end>.npz
  ohlc_path_<start>_<end>.npz
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import torch

from config import DEFAULT_BINS, DEFAULT_PARQUET
from data.dataset import ParquetDataConfig, ParquetDataset, _RollingDatasetState
from data.scaler import PerCodeGroupedScaler
from data.schema import validate_prediction_cache_keys
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from torch.utils.data import DataLoader
from scripts.build_ohlc_path import build_ohlc_path

CENTERS52 = np.linspace(-0.255, 0.255, 52)

ROLLING_SCOPES = ("e2", "e3", "e4")
ROLLING_DEFAULT_SCALER_PATH = "logs/rolling_e4/scaler_rolling_e4.pkl"
PER_CODE_DEFAULT_SCALER_PATH = "logs/scaler_per_code.pkl"


def resolve_eval_mode_scope(run_cfg: dict, cli_scope: str | None = None) -> tuple[str, str | None]:
    """评估 mode/scope：优先 checkpoint preprocessing，CLI --rolling_scope 仅做一致性校验（异 scope 抛错）。"""
    metadata = run_cfg.get("preprocessing") or {}
    mode = metadata.get("mode", "per_code")
    if mode not in {"per_code", "rolling"}:
        raise ValueError(f"checkpoint preprocessing mode 不支持: {mode}")
    scope = metadata.get("scope")
    if mode == "rolling" and scope is None:
        scope = "e4"
    if cli_scope is not None:
        if cli_scope not in ROLLING_SCOPES:
            raise ValueError(f"rolling scope 非法: {cli_scope!r}，仅支持 e2/e3/e4")
        if mode == "rolling" and scope is not None and cli_scope != scope:
            raise ValueError(f"rolling scope 不匹配：checkpoint={scope!r} vs 请求={cli_scope!r}")
        if mode == "rolling":
            scope = cli_scope
    return mode, scope


def resolve_eval_scaler_path(run_cfg: dict, cli_override: str | None = None) -> str:
    """scaler 路径优先级：CLI > preprocessing.state_path/scaler_path/SCALER_PATH > 顶层 SCALER_PATH > 默认。"""
    if cli_override:
        return cli_override
    metadata = run_cfg.get("preprocessing") or {}
    mode = metadata.get("mode", "per_code")
    return (
        metadata.get("state_path") or metadata.get("scaler_path") or metadata.get("SCALER_PATH")
        or run_cfg.get("SCALER_PATH")
        or (ROLLING_DEFAULT_SCALER_PATH if mode == "rolling" else PER_CODE_DEFAULT_SCALER_PATH)
    )


def resolve_latest_checkpoint() -> str:
    cands = sorted(glob.glob("logs/run_*/best_model.pth"))
    if not cands:
        raise FileNotFoundError(
            "未找到 logs/run_*/best_model.pth，请用 --checkpoint 指定"
        )
    return cands[-1]


def load_checkpoint_config(ckpt_path: str) -> dict:
    cfg_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
    if not os.path.exists(cfg_path):
        raise FileNotFoundError(f"checkpoint 同目录缺少 config.json: {cfg_path}")
    with open(cfg_path) as f:
        run_cfg = json.load(f)
    mc = run_cfg.get("CNNTransformerConfig") or {}
    mc["pure_reg"] = bool(run_cfg.get("PURE_REG", False))
    return mc, run_cfg


def build_scaler(
    parquet: str,
    train_start: str,
    train_end: str,
    max_codes: int | None,
    scaler_path: str,
    mode: str = "per_code",
    scope: str | None = None,
):
    if mode == "rolling":
        # rolling 不拟合：必须复用训练 state，异 scope 直接拒绝（不静默复用）。
        if not os.path.exists(scaler_path):
            raise FileNotFoundError(f"rolling evaluation 必须提供 rolling state: {scaler_path}")
        state = _RollingDatasetState.load(scaler_path)
        if scope is not None and state.normalizer.config.scope != scope:
            raise ValueError(
                f"rolling scope 不匹配：state={state.normalizer.config.scope!r} vs 请求={scope!r}"
            )
        print(f"[pipeline] 复用 rolling state({state.normalizer.config.scope}): {scaler_path}")
        return state
    if os.path.exists(scaler_path):
        try:
            cached = PerCodeGroupedScaler.load(scaler_path)
            if cached.fitted:
                print(f"[pipeline] 复用已存在的 scaler: {scaler_path}")
                return cached
        except Exception:
            print(f"[pipeline] scaler 损坏，准备重拟合")
    print(f"[pipeline] 拟合 PerCodeGroupedScaler ...")
    ds = ParquetDataset(
        ParquetDataConfig(
            parquet_path=parquet,
            seq_len=60,
            horizon=5,
            bins=list(DEFAULT_BINS),
            batch_size=256,
            num_workers=0,
            normalize="per_code",
            max_codes=max_codes,
            role="training",
            start_date=train_start,
            end_date=train_end,
        )
    )
    os.makedirs(os.path.dirname(os.path.abspath(scaler_path)), exist_ok=True)
    ds.scaler_stats.save(scaler_path)
    print(f"[pipeline] scaler saved: {scaler_path}")
    return ds.scaler_stats


def run_inference(
    ckpt_path: str,
    parquet: str,
    start: str,
    end: str,
    scaler_stats,
    batch_size: int,
    num_workers: int,
    max_codes: int | None,
    max_windows_per_code: int | None,
    out_path: str,
    mode: str = "per_code",
    scope: str | None = None,
    feature_cols: list[str] | None = None,
):
    mc, run_cfg = load_checkpoint_config(ckpt_path)
    pure_reg = mc.get("pure_reg", False)
    featurenum = int(mc.get("featurenum", 45))
    seq_len = int(run_cfg.get("SEQ_LEN", 60))

    model_cfg = ModelConfig(
        featurenum=featurenum,
        seq_len=seq_len,
        num_classes=52,
        cnn_out_channels=int(mc.get("cnn_out_channels", 128)),
        cnn_kernel_sizes=list(mc.get("cnn_kernel_sizes", [1, 3, 5, 7, 10])),
        d_model=int(mc.get("d_model", 256)),
        nhead=int(mc.get("nhead", 8)),
        num_encoder_layers=int(mc.get("num_encoder_layers", 4)),
        dropout_rate=float(mc.get("dropout_rate", 0.3)),
    )
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = CNNTransformer(model_cfg).to(device)
    model.load_state_dict(torch.load(ckpt_path, map_location=device), strict=True)
    model.eval()
    print(f"[pipeline] model loaded: {ckpt_path}, featurenum={featurenum}, device={device}")

    ds = ParquetDataset(
        ParquetDataConfig(
            parquet_path=parquet,
            seq_len=seq_len,
            horizon=5,
            bins=list(DEFAULT_BINS),
            batch_size=batch_size,
            num_workers=0,
            normalize=mode,
            rolling_scope=(scope or "e4"),
            max_codes=max_codes,
            max_windows_per_code=max_windows_per_code,
            start_date=start,
            end_date=end,
            feature_cols=feature_cols,
            role="evaluation",
        ),
        scaler_stats=scaler_stats,
    )
    if featurenum != ds.num_features:
        raise ValueError(
            f"特征数不一致: checkpoint={featurenum} vs 数据集={ds.num_features}"
        )

    loader = DataLoader(ds, batch_size=batch_size, shuffle=False, num_workers=num_workers, pin_memory=False)

    all_probs, all_true_ret, all_dates, all_codes, all_ret_pred = [], [], [], [], []
    offset = 0
    with torch.no_grad():
        for xb, yb, *_ in loader:
            n = xb.shape[0]
            out = model(xb.to(device))
            if isinstance(out, tuple) and len(out) == 2:
                logits, ret_pred = out
                all_ret_pred.append(ret_pred.cpu().numpy())
            else:
                logits = out
            probs = torch.softmax(logits, dim=1).cpu().numpy()
            all_probs.append(probs)
            # 真值和日期
            tr = np.array([
                float(ds.groups[ds.index[offset + i][0]]["future_ret"][
                    ds.index[offset + i][1] + seq_len - 1
                ]) for i in range(n)
            ])
            pairs = [ds.index[offset + i] for i in range(n)]
            dt = np.array([
                ds.groups[p[0]]["kline_time"][p[1] + seq_len - 1] for p in pairs
            ])
            all_codes.append(np.asarray([p[0] for p in pairs]))
            all_true_ret.append(tr)
            all_dates.append(dt)
            offset += n

    probs = np.concatenate(all_probs)
    true_ret = np.concatenate(all_true_ret)
    exp_ret = np.concatenate(all_ret_pred) if pure_reg else (probs * CENTERS52).sum(axis=1)
    dates = np.concatenate(all_dates)
    codes = np.concatenate(all_codes)

    cache = {"exp_ret": exp_ret, "true_ret": true_ret, "dates": dates, "codes": codes}
    validate_prediction_cache_keys(cache.keys(), "run_eval_pipeline")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    np.savez(out_path, **cache)
    print(f"[pipeline] preds cache saved: {out_path} ({len(exp_ret):,} samples)")


def main():
    args = parse_args()

    ckpt_path = resolve_latest_checkpoint() if not args.checkpoint else args.checkpoint
    ckpt_stem = os.path.splitext(os.path.basename(ckpt_path))[0]
    _, run_cfg = load_checkpoint_config(ckpt_path)
    parquet = args.parquet if args.parquet else run_cfg.get("PARQUET_PATH", DEFAULT_PARQUET)
    train_start = args.train_start if args.train_start else run_cfg.get("TRAIN_START", "2013-01-01")
    train_end = args.train_end if args.train_end else run_cfg.get("TRAIN_END", "2025-06-30")
    start = args.start if args.start else run_cfg.get("VAL_START", "2026-01-01")
    end = args.end if args.end else run_cfg.get("VAL_END", "2026-08-31")
    max_codes = args.max_codes if args.max_codes > 0 else None
    mode, scope = resolve_eval_mode_scope(run_cfg, getattr(args, "rolling_scope", None))
    scaler_path = resolve_eval_scaler_path(run_cfg, args.scaler_path)
    feature_cols = (run_cfg.get("preprocessing") or {}).get("feature_cols")

    ts = time.strftime("%Y%m%d_%H%M%S")
    preds_out = args.preds_out or f"logs/preds_{ckpt_stem}_{end}.npz"
    ohlc_out = args.ohlc_out or f"logs/ohlc_path_{start}_{end}.npz"

    print("=" * 60)
    print(f"[pipeline] checkpoint: {ckpt_path}")
    print(f"[pipeline] parquet: {parquet}")
    print(f"[pipeline] 推理时间: {start} ~ {end}")
    print(f"[pipeline] mode/scope: {mode}" + (f"/{scope}" if mode == "rolling" else ""))
    print(f"[pipeline] scaler: {scaler_path}")
    print(f"[pipeline] preds -> {preds_out}")
    print(f"[pipeline] ohlc  -> {ohlc_out}")
    print("=" * 60)

    if not args.ohlc_only:
        scaler_stats = build_scaler(parquet, train_start, train_end, max_codes, scaler_path, mode, scope)
        run_inference(
            ckpt_path=ckpt_path,
            parquet=parquet,
            start=start,
            end=end,
            scaler_stats=scaler_stats,
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            max_codes=max_codes,
            max_windows_per_code=args.max_windows_per_code,
            out_path=preds_out,
            mode=mode,
            scope=scope,
            feature_cols=feature_cols,
        )

    if not args.preds_only:
        ohlc = build_ohlc_path(parquet, start, end, horizon=5)
        os.makedirs(os.path.dirname(os.path.abspath(ohlc_out)), exist_ok=True)
        np.savez(ohlc_out, **ohlc)
        print(f"[pipeline] ohlc path saved: {ohlc_out} ({len(ohlc['codes']):,} rows)")

    print(f"[pipeline] 完成")


def parse_args():
    p = argparse.ArgumentParser(
        description="全流程评估：scaler → 推理缓存 → OHLC 路径表。"
        "五项取数：IC/ICIR、top-bottom spread、换手成本后收益（run_backtest --cost_rate）、"
        "fallback 比例与 winsor 统计（config.json preprocessing.rolling_audit）；"
        "回测口径 T决策→T+1 open买→T+6 open卖见 backtest/engine.py。",
    )
    p.add_argument("--checkpoint", default=None, help="best_model.pth，默认取最新")
    p.add_argument("--parquet", default=None, help="parquet 路径，默认从 config.json 读")
    p.add_argument("--train_start", default=None, help="训练集起始，默认从 config.json 读")
    p.add_argument("--train_end", default=None, help="训练集截止，默认从 config.json 读")
    p.add_argument("--start", default=None, help="评估/回测起始，默认 2026-01-01")
    p.add_argument("--end", default=None, help="评估/回测截止，默认 2026-08-31")
    p.add_argument("--max_codes", type=int, default=0, help="限制股票数；<=0 表示全市场")
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--batch_size", type=int, default=512)
    p.add_argument("--num_workers", type=int, default=0)
    p.add_argument("--scaler_path", default=None, help="scaler 路径，默认从 config.json 读")
    p.add_argument("--rolling_scope", choices=list(ROLLING_SCOPES), default=None,
                   help="仅 rolling：声明期望 scope，与 checkpoint/STATE 不一致直接报错（不静默复用）")
    p.add_argument("--preds_out", default=None, help="推理缓存 npz 保存路径")
    p.add_argument("--ohlc_out", default=None, help="OHLC 路径表 npz 保存路径")
    p.add_argument("--ohlc-only", action="store_true", help="仅生成 OHLC 路径，跳过推理")
    p.add_argument("--preds-only", action="store_true", help="仅推理，跳过 OHLC 生成")
    return p.parse_args()


if __name__ == "__main__":
    main()
