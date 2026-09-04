"""Parquet 直通训练入口：quant 最新因子数据 -> CNNTransformer -> EMDLoss

链路（per-code 共识）：
  data/test/train_data/train_data_v1_*.parquet (45特征=39+6 mask, 11M行, G6/G7已剔除)
    -> ParquetDataset (is_trading过滤, future_ret=close[t+5]/close[t]-1 52类, per-code分组归一化)
    -> CNNTransformer (featurenum=45, seq_len=60)
    -> EMDLoss (有序分类)
    -> Trainer (早停 + 调度)

使用：
  uv run --project . python train.py --max_codes 20 --epochs 2 --batch_size 256
  uv run --project . python train.py --train_start 2013-01-01 --train_end 2023-12-31 --val_start 2024-01-01 --val_end 2025-12-31

与旧链路兼容：
  旧 main2.py 依赖 processed_data_train/*.npz，本脚本完全替代，无需中间 npz，特征维度由 8 -> 55，标签由 amp sum -> future 5d return
"""
import argparse
import logging
import os
import numpy as np
import torch

from data.dataset import ParquetDataConfig, ParquetDataset
from models.cnn_transformer.model import CNNTransformer
from models.cnn_transformer.config import ModelConfig
from training import Trainer
from visualization import Visualizer
from log_manager import LoggerManager
from criterion.emd_loss import EMDLoss

# -------------------- 默认配置（可经命令行覆盖） --------------------
DEFAULT_PARQUET = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
# 与 main2 保持一致的 BINS（52类）
DEFAULT_BINS = (np.linspace(-25, 25, 51) / 100).tolist()

config = {
    'DEVICE': 'cuda' if torch.cuda.is_available() else 'cpu',
    # 数据（per-code 共识：45特征=39+6 mask，G6/G7已剔除，zscore已删除）
    'PARQUET_PATH': DEFAULT_PARQUET,
    'BINS': DEFAULT_BINS,
    'SEQ_LEN': 60,
    'HORIZON': 5,
    'BATCH_SIZE': 256,
    'NUM_WORKERS': 4,
    'TRAIN_START': "2013-01-01",
    'TRAIN_END': "2025-06-30",
    'VAL_START': "2025-07-01",
    'VAL_END': "2025-12-31",
    'TEST_START': "2026-01-01",
    'TEST_END': None,  # 至今（当前 parquet 仅至 2025-12-31，test 暂空，待增量数据）
    'NORMALIZE': "per_code",
    'SCALER_PATH': "logs/scaler_per_code.pkl",
    'MAX_CODES': None,  # 调试用，小样本
    'MAX_WINDOWS_PER_CODE': None,

    # 模型（适配 45 特征，per-code 12+7+3+6+5+6=39+6 mask）
    "model": "CNNTransformer",
    "CNNTransformerConfig": {
        'featurenum': 45,  # per-code 45，将在运行时根据实际特征数校正
        'seq_len': 60,
        'num_classes': 52,  # len(BINS)+1
        'cnn_out_channels': 128,
        'd_model': 256,
        'nhead': 8,
        "cnn_kernel_sizes": [1, 3, 5, 7, 10],
        'num_encoder_layers': 4,
        'dropout_rate': 0.3,
    },

    # 训练
    "criterion": "EMDLoss",
    "EMLossConfig": dict(p=2, label_smoothing=True, smooth_eps=0.1),
    "scheduler": "ReduceLROnPlateau",
    'LEARNING_RATE': 1e-4,
    'WEIGHT_DECAY': 1e-5,
    'EPOCHS': 50,
    'PATIENCE': 10,
    'LOG_DIR': './logs',
}

# 派生
config['num_classes'] = len(config['BINS']) + 1
config["CNNTransformerConfig"]['num_classes'] = len(config['BINS']) + 1
config["CNNTransformerConfig"]['seq_len'] = config['SEQ_LEN']


def parse_args():
    p = argparse.ArgumentParser(description="Parquet 直通训练")
    p.add_argument("--parquet", type=str, default=config['PARQUET_PATH'], help="parquet 路径")
    p.add_argument("--train_start", type=str, default=config['TRAIN_START'])
    p.add_argument("--train_end", type=str, default=config['TRAIN_END'])
    p.add_argument("--val_start", type=str, default=config['VAL_START'])
    p.add_argument("--val_end", type=str, default=config['VAL_END'])
    p.add_argument("--test_start", type=str, default=config['TEST_START'])
    p.add_argument("--test_end", type=str, default=config['TEST_END'])
    p.add_argument("--seq_len", type=int, default=config['SEQ_LEN'])
    p.add_argument("--horizon", type=int, default=config['HORIZON'])
    p.add_argument("--batch_size", type=int, default=config['BATCH_SIZE'])
    p.add_argument("--num_workers", type=int, default=config['NUM_WORKERS'])
    p.add_argument("--epochs", type=int, default=config['EPOCHS'])
    p.add_argument("--lr", type=float, default=config['LEARNING_RATE'])
    p.add_argument("--max_codes", type=int, default=None, help="调试：仅取前 N 只股票")
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--no_val", action="store_true", help="不使用验证集")
    p.add_argument("--smoke", action="store_true", help="冒烟测试：max_codes=20, epochs=1, batch 256")
    return p.parse_args()


def main():
    args = parse_args()
    if args.smoke:
        args.max_codes = 20
        args.epochs = 1
        config['EPOCHS'] = 1
        config['BATCH_SIZE'] = 256
        args.batch_size = 256
        print(">>> SMOKE 模式：max_codes=20, epochs=1")

    # 覆盖 config
    config['PARQUET_PATH'] = args.parquet
    config['SEQ_LEN'] = args.seq_len
    config['HORIZON'] = args.horizon
    config['BATCH_SIZE'] = args.batch_size
    config['NUM_WORKERS'] = args.num_workers
    config['TRAIN_START'] = args.train_start
    config['TRAIN_END'] = args.train_end
    config['VAL_START'] = args.val_start
    config['VAL_END'] = args.val_end
    config['TEST_START'] = args.test_start
    config['TEST_END'] = args.test_end
    config['EPOCHS'] = args.epochs
    config['LEARNING_RATE'] = args.lr
    config['MAX_CODES'] = args.max_codes
    config['MAX_WINDOWS_PER_CODE'] = args.max_windows_per_code
    if args.smoke and args.max_codes is None:
        config['MAX_CODES'] = 20
    config["CNNTransformerConfig"]['seq_len'] = config['SEQ_LEN']

    print("=" * 60)
    print("Parquet 直通训练配置:")
    for k, v in config.items():
        if k in ("BINS", "CNNTransformerConfig", "EMLossConfig"):
            continue
        print(f"  {k}: {v}")
    print(f"  BINS: len={len(config['BINS'])} {config['BINS'][:3]}...{config['BINS'][-3:]}")
    print(f"  CNNTransformerConfig: {config['CNNTransformerConfig']}")
    print("=" * 60)

    # 日志
    # LoggerManager 会将 config 持久化到 logs/run_xxx/config.json，需确保可序列化
    log_config = {k: (v if not isinstance(v, np.ndarray) else v.tolist()) for k, v in config.items()}
    logger_manager = LoggerManager(log_dir=config['LOG_DIR'], config=log_config)
    logger = logging.getLogger(__name__)
    logger.info("=== Parquet 训练开始 ===")
    config["run_log_dir"] = logger_manager.run_log_dir

    # 数据集
    logger.info("=== 初始化数据集 ===")
    parquet_cfg = ParquetDataConfig(
        parquet_path=config['PARQUET_PATH'],
        seq_len=config['SEQ_LEN'],
        horizon=config['HORIZON'],
        bins=config['BINS'],
        batch_size=config['BATCH_SIZE'],
        num_workers=config['NUM_WORKERS'],
        normalize=config['NORMALIZE'],
        scaler_path=config['SCALER_PATH'],
        max_codes=config['MAX_CODES'],
        max_windows_per_code=config['MAX_WINDOWS_PER_CODE'],
    )

    # 若 smoke 模式，使用更小的时间范围以加速
    if args.smoke:
        # 仍用全量时间但限制 codes，足够快
        pass

    train_start = None if args.no_val else config['TRAIN_START']
    train_end = None if args.no_val else config['TRAIN_END']
    val_start = None if args.no_val else config['VAL_START']
    val_end = None if args.no_val else config['VAL_END']
    test_start = None if args.no_val else config['TEST_START']
    test_end = None if args.no_val else config['TEST_END']

    # 若用户未指定验证集时间但 smoke，也创建验证集以测试完整链路
    # 当前仅训练/验证进入 Trainer；test 需全量数据落盘后评估，smoke 时不创建以免空数据报错
    train_loader, val_loader, scaler_stats = ParquetDataset.create_dataloaders(
        parquet_cfg,
        train_start=train_start,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        scaler_path=config['SCALER_PATH'],
    )
    logger.info(f"训练集样本数: {len(train_loader.dataset):,}")
    if val_loader:
        logger.info(f"验证集样本数: {len(val_loader.dataset):,}")
    # test 集日志（不入 Trainer，仅记录，待 2026 数据增量后可用）
    if test_start:
        logger.info(f"测试集预留: {test_start} ~ {test_end or '至今'} (当前 parquet 至 2025-12-31，暂为空)")

    # 校验 val 非空（新切分 2025下半年样本较少，smoke 20股可能仅 ~2k 窗口）
    if val_loader and len(val_loader.dataset) == 0:
        logger.warning("验证集为空，请检查 VAL_START/VAL_END 与 max_codes 组合")

    # 自动校正 featurenum
    actual_featurenum = train_loader.dataset.num_features
    if actual_featurenum != config["CNNTransformerConfig"]['featurenum']:
        logger.warning(f"特征数不匹配: config={config['CNNTransformerConfig']['featurenum']} vs 实际={actual_featurenum}，已自动校正")
        config["CNNTransformerConfig"]['featurenum'] = actual_featurenum

    # 模型
    logger.info("=== 初始化模型 ===")
    model_cfg = ModelConfig(**config["CNNTransformerConfig"])
    model = CNNTransformer(model_cfg).to(config['DEVICE'])
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"总参数量: {total_params:,}")
    logger.info(f"可训练参数量: {trainable_params:,}")
    logger.info(f"可训练比例: {100*trainable_params/total_params:.2f}%")
    # 打印输入维度校验
    logger.info(f"模型输入: [batch, featurenum={model_cfg.featurenum}, seq_len={model_cfg.seq_len}] -> {model_cfg.num_classes} 类")

    # 损失 & 优化器
    logger.info("=== 初始化损失与优化器 ===")
    criterion = EMDLoss(num_classes=config['num_classes'], **config['EMLossConfig'])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['LEARNING_RATE'], weight_decay=config['WEIGHT_DECAY'])
    if config['scheduler'] == "ReduceLROnPlateau":
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)
    elif config['scheduler'] == "CosineAnnealingWarmRestarts":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=10, T_mult=2, eta_min=1e-6)
    else:
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)

    # 训练
    logger.info("=== 开始训练 ===")
    trainer = Trainer(
        model=model,
        config=config,
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

    # 可视化
    train_losses, val_losses, train_accs, val_accs = trainer.get_training_history()
    try:
        vis_path = os.path.join(config["run_log_dir"], "training_curve.png")
        Visualizer.plot_training_curves(train_losses, val_losses, train_accs, val_accs, save_path=vis_path)
        logger.info(f"训练曲线已保存: {vis_path}")
    except Exception as e:
        logger.warning(f"可视化失败: {e}")

    # 加载最佳模型
    best_path = os.path.join(config["run_log_dir"], "best_model.pth")
    if os.path.exists(best_path):
        model.load_state_dict(torch.load(best_path, map_location=config['DEVICE']))
        logger.info(f"已加载最佳模型: {best_path}")
    else:
        logger.warning(f"未找到最佳模型: {best_path}")

    logger.info("=== 训练结束 ===")
    print(f"\n训练完成，日志目录: {config['run_log_dir']}")
    print(f"最佳模型: {best_path}")
    print(f"训练曲线: {os.path.join(config['run_log_dir'], 'training_curve.png')}")


if __name__ == "__main__":
    main()
