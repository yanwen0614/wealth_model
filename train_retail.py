"""散户友好模型训练入口：Parquet → RetailFriendlyModel → RetailLoss → RetailTrainer.

设计：
  - 复用现有数据管道（ParquetDataset, feature_cache, 归一化）
  - 模型改为二分类（胜率概率）+ 回归（预期涨幅）双头
  - 损失函数使用 AsymmetricLoss（面向高 precision，γ_neg=4 强罚 FP）
  - 训练后自动校准决策阈值，目标验证集 precision ≥ 75%
  - 早停复用 EarlyStopping，调度器复用 ReduceLROnPlateau

使用：
  uv run --project . python train_retail.py --smoke --num_workers 0
  uv run --project . python train_retail.py --epochs 50 --batch_size 256
  uv run --project . python train_retail.py --normalize relative --lr 3e-4
"""

import argparse
import json
import logging
import os
import random
from typing import Any, cast

import numpy as np
import torch

from config.defaults import make_default_config
from data.dataset import ParquetDataConfig, ParquetDataset
from data.feature_cache import resolve_cache_root
from log_manager import LoggerManager
from models.retail_friendly.config import RetailModelConfig, RetailInferenceConfig
from models.retail_friendly.loss import RetailLoss
from models.retail_friendly.model import RetailFriendlyModel
from training.factory import build_optimizer_scheduler
from training.retail_trainer import RetailTrainer

config = make_default_config()
ROLLING_SCOPES = ("e0", "e1", "e2", "e3", "e4", "e5")


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="散户友好模型训练")
    # 数据
    p.add_argument("--parquet", type=str, default=config["PARQUET_PATH"])
    p.add_argument("--train_start", type=str, default=config["TRAIN_START"])
    p.add_argument("--train_end", type=str, default=config["TRAIN_END"])
    p.add_argument("--val_start", type=str, default=config["VAL_START"])
    p.add_argument("--val_end", type=str, default=config["VAL_END"])
    p.add_argument("--test_start", type=str, default=config["TEST_START"])
    p.add_argument("--test_end", type=str, default=config["TEST_END"])
    # 窗口
    p.add_argument("--seq_len", type=int, default=config["SEQ_LEN"])
    p.add_argument("--horizon", type=int, default=config["HORIZON"])
    # 训练
    p.add_argument("--batch_size", type=int, default=config["BATCH_SIZE"])
    p.add_argument("--num_workers", type=int, default=config["NUM_WORKERS"])
    p.add_argument("--epochs", type=int, default=config["EPOCHS"])
    p.add_argument("--patience", type=int, default=config["PATIENCE"])
    p.add_argument("--lr", type=float, default=config["LEARNING_RATE"])
    p.add_argument("--seed", type=int, default=config["SEED"])
    # 调试
    p.add_argument("--max_codes", type=int, default=None)
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--smoke", action="store_true")
    # 归一化（复用现有策略）
    p.add_argument("--normalize", choices=["per_code", "rolling", "relative"],
                   default=config["NORMALIZE"])
    p.add_argument("--rolling_scope", choices=list(ROLLING_SCOPES),
                   default=config["ROLLING_SCOPE"])
    # 特征
    p.add_argument("--feature_cols", nargs="*", default=None)
    p.add_argument("--featurenum", type=int, default=None)
    # 零售模型特有
    p.add_argument("--gamma_neg", type=float, default=4.0,
                   help="AsymmetricLoss 负类聚焦参数（高→强罚FP→高precision）")
    p.add_argument("--lambda_reg", type=float, default=0.3,
                   help="回归辅助损失权重")
    p.add_argument("--default_threshold", type=float, default=0.65,
                   help="初始决策阈值（训练后由校准覆盖）")
    p.add_argument("--target_precision", type=float, default=0.75,
                   help="阈值校准目标 precision")
    # 缓存
    p.add_argument("--cache_dir", type=str, default=config["CACHE_DIR"])
    p.add_argument("--no_cache", action="store_true")
    p.add_argument("--rebuild_cache", action="store_true")
    return p.parse_args(argv)


def configure_preprocessing(base_cfg: dict, normalize: str, rolling_scope: str = "e5") -> None:
    """配置归一化（复用 train.py 同一逻辑）。"""
    if normalize not in {"per_code", "rolling", "relative"}:
        raise ValueError(f"未知 normalize: {normalize}")
    base_cfg["NORMALIZE"] = normalize
    if normalize == "per_code":
        base_cfg["SCALER_PATH"] = "logs/scaler_per_code.pkl"
        base_cfg["LOG_DIR"] = "./logs/retail_per_code"
    elif normalize == "rolling":
        if rolling_scope not in ROLLING_SCOPES:
            raise ValueError(f"未知 rolling_scope: {rolling_scope!r}")
        base_cfg["ROLLING_SCOPE"] = rolling_scope
        base_cfg["SCALER_PATH"] = f"logs/rolling_{rolling_scope}/scaler_rolling_{rolling_scope}.pkl"
        base_cfg["LOG_DIR"] = f"./logs/retail_rolling_{rolling_scope}"
    else:  # relative
        base_cfg["SCALER_PATH"] = None
        base_cfg["LOG_DIR"] = "./logs/retail_relative"


def set_all_seeds(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def resolve_featurenum(requested: int | None, actual: int) -> int:
    if requested is not None and requested != actual:
        raise ValueError(f"--featurenum 与实测维度不符: requested={requested} actual={actual}")
    return actual


def main():
    args = parse_args()
    set_all_seeds(args.seed)

    # Smoke
    if args.smoke:
        args.max_codes = 20
        args.epochs = 1
        config["EPOCHS"] = 1
        config["BATCH_SIZE"] = 256
        args.batch_size = 256
        print(">>> SMOKE 模式: max_codes=20, epochs=1")

    # ── 配置构建 ──
    cfg: dict = dict(config)  # copy
    cfg["PARQUET_PATH"] = args.parquet
    cfg["SEQ_LEN"] = args.seq_len
    cfg["HORIZON"] = args.horizon
    cfg["BATCH_SIZE"] = args.batch_size
    cfg["NUM_WORKERS"] = args.num_workers
    cfg["TRAIN_START"] = args.train_start
    cfg["TRAIN_END"] = args.train_end
    cfg["VAL_START"] = args.val_start
    cfg["VAL_END"] = args.val_end
    cfg["EPOCHS"] = args.epochs
    cfg["PATIENCE"] = args.patience
    cfg["LEARNING_RATE"] = args.lr
    cfg["SEED"] = args.seed
    cfg["MAX_CODES"] = args.max_codes
    cfg["MAX_WINDOWS_PER_CODE"] = args.max_windows_per_code
    cfg["ROLLING_SCOPE"] = args.rolling_scope
    cfg["FEATURE_COLS"] = args.feature_cols
    # 零售模型专属
    cfg["RETAIL_GAMMA_NEG"] = args.gamma_neg
    cfg["RETAIL_LAMBDA_REG"] = args.lambda_reg
    cfg["RETAIL_DEFAULT_THRESHOLD"] = args.default_threshold
    cfg["RETAIL_TARGET_PRECISION"] = args.target_precision
    # 缓存
    cfg["CACHE_ENABLED"] = not args.no_cache
    cfg["CACHE_DIR"] = args.cache_dir
    cfg["REBUILD_CACHE"] = args.rebuild_cache

    configure_preprocessing(cfg, args.normalize, args.rolling_scope)

    # 打印配置
    print("=" * 60)
    print("散户友好模型训练配置:")
    for k, v in cfg.items():
        if k in ("BINS", "CNNTransformerConfig", "EMLossConfig"):
            continue
        print(f"  {k}: {v}")
    print(f"  BINS: len={len(cfg['BINS'])}")
    print(f"  RetailLoss: gamma_neg={args.gamma_neg}, lambda_reg={args.lambda_reg}")
    if cfg["CACHE_ENABLED"]:
        print(f"  CACHE: enabled, rebuild={cfg['REBUILD_CACHE']}, root={resolve_cache_root(cfg['CACHE_DIR'])}")
    else:
        print("  CACHE: disabled")
    print("=" * 60)

    # ── 日志 ──
    log_config = {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in cfg.items()}
    logger_manager = LoggerManager(log_dir=cfg["LOG_DIR"], config=log_config)
    logger = logging.getLogger(__name__)
    logger.info("=== 散户模型训练开始 ===")
    cfg["run_log_dir"] = logger_manager.run_log_dir

    # ── 数据集（复用现有 ParquetDataset） ──
    logger.info("=== 初始化数据集 ===")
    parquet_cfg = ParquetDataConfig(
        parquet_path=cfg["PARQUET_PATH"],
        seq_len=cfg["SEQ_LEN"],
        horizon=cfg["HORIZON"],
        bins=cfg["BINS"],
        batch_size=cfg["BATCH_SIZE"],
        num_workers=cfg["NUM_WORKERS"],
        normalize=cfg["NORMALIZE"],
        rolling_scope=cfg["ROLLING_SCOPE"],
        feature_cols=cfg["FEATURE_COLS"],
        scaler_path=cfg["SCALER_PATH"],
        max_codes=cfg["MAX_CODES"],
        max_windows_per_code=cfg["MAX_WINDOWS_PER_CODE"],
        cache_enabled=cfg["CACHE_ENABLED"],
        cache_dir=cfg["CACHE_DIR"],
        rebuild_cache=cfg["REBUILD_CACHE"],
    )

    train_start = None if args.smoke else cfg["TRAIN_START"]
    val_start = None if args.smoke else cfg["VAL_START"]

    train_loader, val_loader, _ = ParquetDataset.create_dataloaders(
        parquet_cfg,
        train_start=train_start,
        train_end=cfg["TRAIN_END"],
        val_start=val_start,
        val_end=cfg["VAL_END"],
        scaler_path=cfg["SCALER_PATH"],
    )
    train_dataset = cast(ParquetDataset, train_loader.dataset)
    actual_featurenum = resolve_featurenum(args.featurenum, train_dataset.num_features)

    logger.info(f"训练集样本数: {len(train_dataset):,}")
    if val_loader is not None:
        logger.info(f"验证集样本数: {len(cast(ParquetDataset, val_loader.dataset)):,}")
        if len(cast(ParquetDataset, val_loader.dataset)) == 0:
            logger.warning("验证集为空，请检查时间范围与 max_codes")

    # ── 模型 ──
    logger.info("=== 初始化模型 ===")
    model_config = RetailModelConfig(
        featurenum=actual_featurenum,
        seq_len=cfg["SEQ_LEN"],
        dropout_rate=cfg.get("CNNTransformerConfig", {}).get("dropout_rate", 0.3),
        lambda_reg=args.lambda_reg,
    )
    model = RetailFriendlyModel(model_config)
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"总参数量: {total_params:,}  可训练: {trainable_params:,}  ({100*trainable_params/total_params:.1f}%)")
    logger.info(f"模型输入: [B, F={actual_featurenum}, T={cfg['SEQ_LEN']}] → p_bin[B] + ret_pred[B]")

    # ── 损失 & 优化器 ──
    logger.info("=== 初始化损失与优化器 ===")
    criterion = RetailLoss(
        gamma_neg=args.gamma_neg,
        lambda_reg=args.lambda_reg,
        huber_delta=cfg.get("HUBER_DELTA", 1.0),
    )
    optimizer, scheduler = build_optimizer_scheduler(model, cfg)
    logger.info(f"损失: RetailLoss(ASL γ_neg={args.gamma_neg} + {args.lambda_reg}×Huber)")
    logger.info(f"优化器: AdamW(lr={cfg['LEARNING_RATE']}, wd={cfg.get('WEIGHT_DECAY', 1e-5)})")

    # ── 训练 ──
    logger.info("=== 开始训练 ===")
    trainer = RetailTrainer(
        model=model,
        config=cfg,
        train_loader=train_loader,
        val_loader=val_loader,
        criterion=criterion,
        optimizer=optimizer,
        scheduler=scheduler,
    )
    try:
        trainer.train()
    except KeyboardInterrupt:
        logger.warning("训练被中断")

    # ── 保存校准报告 ──
    history = trainer.get_training_history()
    report_path = os.path.join(cfg["run_log_dir"], "calibration_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(history["calibration_report"], f, indent=2, ensure_ascii=False)
    logger.info(f"校准报告已保存: {report_path}")

    # ── 保存最终指标汇总 ──
    final_metrics = {
        "run_log_dir": cfg["run_log_dir"],
        "calibrated_threshold": history["calibrated_threshold"],
        "calibration": history["calibration_report"],
        "final_train_loss": history["train_losses"][-1] if history["train_losses"] else None,
        "final_val_loss": history["val_losses"][-1] if history["val_losses"] else None,
        "final_val_precision": history["val_precisions"][-1] if history["val_precisions"] else None,
        "final_val_f1": history["val_f1s"][-1] if history["val_f1s"] else None,
        "best_val_loss": min(history["val_losses"]) if history["val_losses"] else None,
        "best_val_precision": max(history["val_precisions"]) if history["val_precisions"] else None,
        "n_epochs_trained": len(history["train_losses"]),
        "config": {
            "normalize": cfg["NORMALIZE"],
            "epochs": cfg["EPOCHS"],
            "batch_size": cfg["BATCH_SIZE"],
            "lr": cfg["LEARNING_RATE"],
            "gamma_neg": args.gamma_neg,
            "lambda_reg": args.lambda_reg,
            "featurenum": actual_featurenum,
            "max_codes": cfg["MAX_CODES"],
        },
    }
    final_path = os.path.join(cfg["run_log_dir"], "final_metrics.json")
    with open(final_path, "w", encoding="utf-8") as f:
        json.dump(final_metrics, f, indent=2, ensure_ascii=False)
    logger.info(f"最终指标已保存: {final_path}")

    # ── 更新推理配置 ──
    infer_cfg = RetailInferenceConfig(
        threshold=history["calibrated_threshold"],
    )
    infer_path = os.path.join(cfg["run_log_dir"], "inference_config.json")
    with open(infer_path, "w", encoding="utf-8") as f:
        # 用 dataclass 的 asdict 避免手动序列化
        import dataclasses
        json.dump(dataclasses.asdict(infer_cfg), f, indent=2, ensure_ascii=False)
    logger.info(f"推理配置已保存: {infer_path}")

    print(f"\n训练完成！日志目录: {cfg['run_log_dir']}")
    print(f"校准后阈值: {history['calibrated_threshold']:.3f}")
    print(f"校准 precision: {history['calibration_report'].get('precision', 'N/A'):.2%}")
    print(f"最佳模型: {os.path.join(cfg['run_log_dir'], 'best_model.pth')}")


if __name__ == "__main__":
    main()
