"""散户友好模型训练入口（T13 thin wrapper）：复用 train.py 公共链路，仅保留零售差异。

差异仅三处：模型/损失经 factory(mode=retail_friendly)装配；落盘 calibration/final/inference
三件套；smoke 时间语义（None 起点）与 retail_* 日志隔离。其余 parse/config/cache/dataloader
全调 train.py 或 training.preprocessing（零行为漂移，checkpoint 留 T14）。
使用：
  uv run --project . python train_retail.py --smoke --num_workers 0
"""
import dataclasses
import json
import logging
import os
from typing import Any, cast

import numpy as np

import train as train_main
from config.defaults import make_default_config
from data.dataset import ParquetDataset
from log_manager import LoggerManager
from models.retail_friendly.config import RetailInferenceConfig
from training import Trainer
from training.factory import build_criterion, build_model, build_optimizer_scheduler
from training.preprocessing import configure_preprocessing as _configure_preprocessing

config = make_default_config()


def parse_args(argv: list[str] | None = None):
    """复用 train.parse_args(retail=True)：参数不消失，零售默认值 lambda0.3/thr0.65。"""
    return train_main.parse_args(argv, retail=True)


def configure_preprocessing(base_cfg: dict, normalize: str, rolling_scope: str = "e5") -> None:
    """兼容旧导入；唯一实现见 training.preprocessing（retail 隔离目录）。"""
    _configure_preprocessing(base_cfg, normalize, rolling_scope, retail=True)


# 兼容旧导入路径（实现复用 train.py，零重复定义）
set_all_seeds = train_main.set_all_seeds
resolve_featurenum = train_main.resolve_featurenum


def save_retail_artifacts(run_log_dir: str, history: dict, cfg: dict, args, featurenum: int) -> None:
    """落盘零售三件套（差异保留）：calibration_report/final_metrics/inference_config。"""
    with open(os.path.join(run_log_dir, "calibration_report.json"), "w", encoding="utf-8") as f:
        json.dump(history["calibration_report"], f, indent=2, ensure_ascii=False)
    tl, vl, vp, vf = history["train_losses"], history["val_losses"], history["val_precisions"], history["val_f1s"]
    final_metrics = {"run_log_dir": run_log_dir, "calibrated_threshold": history["calibrated_threshold"],
        "calibration": history["calibration_report"], "final_train_loss": tl[-1] if tl else None,
        "final_val_loss": vl[-1] if vl else None, "final_val_precision": vp[-1] if vp else None,
        "final_val_f1": vf[-1] if vf else None, "best_val_loss": min(vl) if vl else None,
        "best_val_precision": max(vp) if vp else None, "n_epochs_trained": len(tl),
        "config": {"normalize": cfg["NORMALIZE"], "epochs": cfg["EPOCHS"], "batch_size": cfg["BATCH_SIZE"],
            "lr": cfg["LEARNING_RATE"], "gamma_neg": getattr(args, "gamma_neg", 4.0),
            "lambda_reg": args.lambda_reg, "featurenum": featurenum, "max_codes": cfg["MAX_CODES"]}}
    with open(os.path.join(run_log_dir, "final_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(final_metrics, f, indent=2, ensure_ascii=False)
    infer_cfg = RetailInferenceConfig(threshold=history["calibrated_threshold"])
    with open(os.path.join(run_log_dir, "inference_config.json"), "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(infer_cfg), f, indent=2, ensure_ascii=False)


def main():
    args = parse_args()
    train_main.set_all_seeds(args.seed)
    if args.smoke:
        args.max_codes = 20
        args.epochs = 1
        config["EPOCHS"] = 1
        config["BATCH_SIZE"] = 256
        args.batch_size = 256
        print(">>> SMOKE 模式: max_codes=20, epochs=1")
    cfg: dict = dict(config)
    train_main.apply_args_to_config(cfg, args, retail=True)
    cfg["CNNTransformerConfig"]["seq_len"] = cfg["SEQ_LEN"]
    print("=" * 60)
    print("散户友好模型训练配置:")
    for k, v in cfg.items():
        if k in ("BINS", "CNNTransformerConfig", "EMLossConfig"):
            continue
        print(f"  {k}: {v}")
    print(f"  BINS: len={len(cfg['BINS'])}")
    print(f"  RetailLoss: gamma_neg={getattr(args, 'gamma_neg', 4.0)}, lambda_reg={args.lambda_reg}")
    print("=" * 60)
    log_config = {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in cfg.items()}
    logger_manager = LoggerManager(log_dir=cfg["LOG_DIR"])
    logger = logging.getLogger(__name__)
    logger.info("=== 散户模型训练开始 ===")
    cfg["run_log_dir"] = logger_manager.run_log_dir
    logger.info("=== 初始化数据集 ===")
    parquet_cfg = train_main.build_parquet_data_config(cfg)
    ts = None if args.smoke else cfg["TRAIN_START"]
    vs = None if args.smoke else cfg["VAL_START"]
    train_loader, val_loader, _ = ParquetDataset.create_dataloaders(parquet_cfg, ts, cfg["TRAIN_END"], vs, cfg["VAL_END"], cfg["SCALER_PATH"])
    actual = train_main.resolve_featurenum(args.featurenum, cast(ParquetDataset, train_loader.dataset).num_features)
    logger.info(f"训练集样本数: {len(cast(ParquetDataset, train_loader.dataset)):,}")
    logger_manager.save_config(log_config)
    model, _mc = build_model(cfg, actual_featurenum=actual, mode="retail_friendly")
    criterion = build_criterion(cfg, mode="retail_friendly")
    optimizer, scheduler = build_optimizer_scheduler(model, cfg)
    trainer = Trainer(model=model, config=cfg, train_loader=train_loader, val_loader=val_loader, criterion=criterion, optimizer=optimizer, scheduler=cast(Any, scheduler))
    try:
        trainer.train()
    except KeyboardInterrupt:
        logger.warning("训练被中断")
    history = trainer.get_training_history()
    assert isinstance(history, dict), f"零售链路期望dict history，实际{type(history)}"
    save_retail_artifacts(cfg["run_log_dir"], history, cfg, args, actual)
    print(f"\n训练完成！日志目录: {cfg['run_log_dir']}\n校准后阈值: {history['calibrated_threshold']:.3f}")


if __name__ == "__main__":
    main()
