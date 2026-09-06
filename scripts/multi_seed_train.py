"""多 seed 训练脚本：从 λ=0.2 开始，多个 seed 独立训练 + λ 随机波动 ±0.005 + 结果汇总

使用：
  uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42,123
  uv run --project . python scripts/multi_seed_train.py --seeds 42,123,2024,7,999 --epochs 50
  uv run --project . python scripts/multi_seed_train.py --smoke --seeds 42 --lambda_reg 0.6 --lambda_jitter 0.01
"""
import argparse
import csv
import logging
import os
import random
from datetime import UTC, datetime

import numpy as np
import torch

from criterion.dual_loss import DualLoss
from criterion.emd_loss import EMDLoss
from criterion.pure_reg_loss import PureRegLoss
from data.dataset import ParquetDataConfig, ParquetDataset
from log_manager import LoggerManager
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from training import Trainer
from visualization import Visualizer

# 与 train.py 保持一致的默认配置
DEFAULT_PARQUET = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
DEFAULT_BINS = (np.linspace(-25, 25, 51) / 100).tolist()

BASE_CONFIG = {
    'DEVICE': 'cuda' if torch.cuda.is_available() else 'cpu',
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
    'TEST_END': None,
    'NORMALIZE': "per_code",
    'SCALER_PATH': "logs/scaler_per_code.pkl",
    'MAX_CODES': None,
    'MAX_WINDOWS_PER_CODE': None,
    "model": "CNNTransformer",
    "CNNTransformerConfig": {
        'featurenum': 45,
        'seq_len': 60,
        'num_classes': 52,
        'cnn_out_channels': 128,
        'd_model': 256,
        'nhead': 8,
        "cnn_kernel_sizes": [1, 3, 5, 7, 10],
        'num_encoder_layers': 4,
        'dropout_rate': 0.3,
    },
    "criterion": "EMDLoss",
    "EMLossConfig": {"p": 2, "label_smoothing": True, "smooth_eps": 0.1},
    "DUAL_HEAD": True,
    "PURE_REG": False,
    "LAMBDA_REG": 0.2,
    "LAMBDA_JITTER": 0.005,
    "HUBER_DELTA": 1.0,
    "scheduler": "ReduceLROnPlateau",
    'LEARNING_RATE': 1e-4,
    'WEIGHT_DECAY': 1e-5,
    'EPOCHS': 50,
    'PATIENCE': 10,
    'LOG_DIR': './logs',
}
BASE_CONFIG['num_classes'] = len(BASE_CONFIG['BINS']) + 1
BASE_CONFIG["CNNTransformerConfig"]['num_classes'] = len(BASE_CONFIG['BINS']) + 1
BASE_CONFIG["CNNTransformerConfig"]['seq_len'] = BASE_CONFIG['SEQ_LEN']


def set_all_seeds(seed: int):
    """设置所有随机种子，确保可复现。"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def parse_args():
    p = argparse.ArgumentParser(description="多 seed 训练脚本")
    p.add_argument("--seeds", type=str, default="42,123,2024", help="用逗号分隔的随机种子列表")
    p.add_argument("--parquet", type=str, default=BASE_CONFIG['PARQUET_PATH'])
    p.add_argument("--train_start", type=str, default=BASE_CONFIG['TRAIN_START'])
    p.add_argument("--train_end", type=str, default=BASE_CONFIG['TRAIN_END'])
    p.add_argument("--val_start", type=str, default=BASE_CONFIG['VAL_START'])
    p.add_argument("--val_end", type=str, default=BASE_CONFIG['VAL_END'])
    p.add_argument("--test_start", type=str, default=BASE_CONFIG['TEST_START'])
    p.add_argument("--test_end", type=str, default=BASE_CONFIG['TEST_END'])
    p.add_argument("--seq_len", type=int, default=BASE_CONFIG['SEQ_LEN'])
    p.add_argument("--horizon", type=int, default=BASE_CONFIG['HORIZON'])
    p.add_argument("--batch_size", type=int, default=BASE_CONFIG['BATCH_SIZE'])
    p.add_argument("--num_workers", type=int, default=BASE_CONFIG['NUM_WORKERS'])
    p.add_argument("--epochs", type=int, default=BASE_CONFIG['EPOCHS'])
    p.add_argument("--patience", type=int, default=BASE_CONFIG['PATIENCE'])
    p.add_argument("--lr", type=float, default=BASE_CONFIG['LEARNING_RATE'])
    p.add_argument("--max_codes", type=int, default=None)
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--no_val", action="store_true", help="不使用验证集")
    p.add_argument("--smoke", action="store_true", help="冒烟模式：max_codes=20, epochs=1")
    p.add_argument("--dual_head", action="store_true", default=True, help=argparse.SUPPRESS)
    p.add_argument("--no_dual_head", action="store_true", help="关闭双头回归，退化为纯 EMD")
    p.add_argument("--pure_reg", action="store_true", help="纯回归消融")
    p.add_argument("--lambda_reg", type=float, default=BASE_CONFIG['LAMBDA_REG'], help="回归权重基准 λ")
    p.add_argument("--lambda_jitter", type=float, default=BASE_CONFIG['LAMBDA_JITTER'], help="λ 随机波动 ± 范围")
    p.add_argument("--huber_delta", type=float, default=BASE_CONFIG['HUBER_DELTA'])
    return p.parse_args()


def run_single_seed(seed: int, cfg: dict, scaler_stats=None):
    """执行单个 seed 的完整训练流程，返回结果字典。"""
    set_all_seeds(seed)
    lambda_val = cfg['LAMBDA_REG'] + np.random.uniform(-cfg['LAMBDA_JITTER'], cfg['LAMBDA_JITTER'])
    lambda_val = max(0.0, lambda_val)

    _ = cfg.get('_timestamp', datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))
    logger_manager = LoggerManager(
        log_dir=cfg['LOG_DIR'],
        config={**cfg, 'seed': seed, 'lambda_actual': lambda_val}
    )
    run_log_dir = logger_manager.run_log_dir
    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info(f"Seed {seed} — λ_actual={lambda_val:.6f} (基准={cfg['LAMBDA_REG']}, jitter=±{cfg['LAMBDA_JITTER']})")
    logger.info(f"日志目录: {run_log_dir}")
    logger.info("=" * 60)

    try:
        parquet_cfg = ParquetDataConfig(
            parquet_path=cfg['PARQUET_PATH'],
            seq_len=cfg['SEQ_LEN'],
            horizon=cfg['HORIZON'],
            bins=cfg['BINS'],
            batch_size=cfg['BATCH_SIZE'],
            num_workers=cfg['NUM_WORKERS'],
            normalize=cfg['NORMALIZE'],
            scaler_path=cfg['SCALER_PATH'],
            max_codes=cfg['MAX_CODES'],
            max_windows_per_code=cfg['MAX_WINDOWS_PER_CODE'],
        )
        train_loader, val_loader, _ = ParquetDataset.create_dataloaders(
            parquet_cfg,
            train_start=cfg['TRAIN_START'],
            train_end=cfg['TRAIN_END'],
            val_start=cfg['VAL_START'],
            val_end=cfg['VAL_END'],
            scaler_path=cfg['SCALER_PATH'],
        )
        logger.info(f"训练集: {len(train_loader.dataset):,}")
        if val_loader:
            logger.info(f"验证集: {len(val_loader.dataset):,}")

        actual_fn = train_loader.dataset.num_features
        model_cfg_dict = dict(cfg['CNNTransformerConfig'])
        if actual_fn != model_cfg_dict['featurenum']:
            logger.warning(f"特征校正: {model_cfg_dict['featurenum']} -> {actual_fn}")
            model_cfg_dict['featurenum'] = actual_fn

        model_cfg = ModelConfig(**model_cfg_dict)
        model = CNNTransformer(model_cfg).to(cfg['DEVICE'])

        if cfg['PURE_REG']:
            criterion = PureRegLoss(num_classes=cfg['num_classes'], huber_delta=cfg['HUBER_DELTA'])
        elif cfg['DUAL_HEAD']:
            criterion = DualLoss(num_classes=cfg['num_classes'], **cfg['EMLossConfig'],
                                 lambda_reg=lambda_val, huber_delta=cfg['HUBER_DELTA'])
        else:
            criterion = EMDLoss(num_classes=cfg['num_classes'], **cfg['EMLossConfig'])

        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg['LEARNING_RATE'],
                                      weight_decay=cfg['WEIGHT_DECAY'])
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)

        local_cfg = dict(cfg)
        local_cfg["run_log_dir"] = run_log_dir
        trainer = Trainer(model=model, config=local_cfg, train_loader=train_loader,
                          val_loader=val_loader, criterion=criterion,
                          optimizer=optimizer, scheduler=scheduler)
        trainer.train()

        train_losses, val_losses, train_accs, val_accs = trainer.get_training_history()
        best_val_loss = min(val_losses) if val_losses else float('inf')
        best_val_acc = max(val_accs) if val_accs else 0.0
        best_val_loss_epoch = val_losses.index(best_val_loss) if val_losses else -1
        total_epochs = len(train_losses)

        try:
            vis_path = os.path.join(run_log_dir, "training_curve.png")
            Visualizer.plot_training_curves(train_losses, val_losses, train_accs, val_accs, save_path=vis_path)
            logger.info(f"训练曲线: {vis_path}")
        except Exception:
            logger.warning("可视化失败", exc_info=True)

        logger.info(
            f"Seed {seed} 完成 — best_val_loss={best_val_loss:.6f}, best_val_acc={best_val_acc:.6f}, "
            f"epochs={total_epochs}")
        return {
            'seed': seed,
            'lambda': lambda_val,
            'best_val_loss': best_val_loss,
            'best_val_acc': best_val_acc,
            'total_epochs': total_epochs,
            'best_val_loss_epoch': best_val_loss_epoch,
            'run_log_dir': run_log_dir,
            'status': 'OK',
        }
    except Exception:
        logger.exception(f"Seed {seed} 训练失败")
        return {
            'seed': seed,
            'lambda': lambda_val,
            'best_val_loss': float('inf'),
            'best_val_acc': 0.0,
            'total_epochs': 0,
            'best_val_loss_epoch': -1,
            'run_log_dir': getattr(logger_manager, 'run_log_dir', 'N/A'),
            'status': 'FAIL',
        }
    finally:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def main():
    args = parse_args()
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    print(f">>> 多 seed 训练启动: seeds={seeds}, λ_基准={args.lambda_reg}, jitter=±{args.lambda_jitter}")

    cfg = dict(BASE_CONFIG)
    if args.smoke:
        args.max_codes = 20
        args.epochs = 1
        cfg['EPOCHS'] = 1
        cfg['BATCH_SIZE'] = 256
        print(">>> SMOKE 模式: max_codes=20, epochs=1")
    if args.no_dual_head:
        cfg['DUAL_HEAD'] = False
        print(">>> 单头模式 (EMD-only)")

    overrides = {
        'PARQUET_PATH': args.parquet, 'SEQ_LEN': args.seq_len, 'HORIZON': args.horizon,
        'BATCH_SIZE': args.batch_size, 'NUM_WORKERS': args.num_workers,
        'TRAIN_START': args.train_start, 'TRAIN_END': args.train_end,
        'VAL_START': args.val_start, 'VAL_END': args.val_end,
        'TEST_START': args.test_start, 'TEST_END': args.test_end,
        'EPOCHS': args.epochs, 'PATIENCE': args.patience,
        'LEARNING_RATE': args.lr, 'MAX_CODES': args.max_codes,
        'MAX_WINDOWS_PER_CODE': args.max_windows_per_code,
        'LAMBDA_REG': args.lambda_reg, 'LAMBDA_JITTER': args.lambda_jitter,
        'HUBER_DELTA': args.huber_delta, 'PURE_REG': args.pure_reg,
    }
    cfg.update(overrides)
    cfg['num_classes'] = len(BASE_CONFIG['BINS']) + 1
    cfg["CNNTransformerConfig"]['num_classes'] = cfg['num_classes']
    cfg["CNNTransformerConfig"]['seq_len'] = cfg['SEQ_LEN']

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    cfg['_timestamp'] = timestamp

    results = []
    for seed in seeds:
        print(f"\n{'='*60}\n>>> 开始 Seed {seed}\n{'='*60}")
        result = run_single_seed(seed, cfg)
        results.append(result)
        print(f">>> Seed {seed} 结果: {result['status']} | "
              f"val_loss={result['best_val_loss']:.6f}, val_acc={result['best_val_acc']:.6f}")

    results.sort(key=lambda r: r['best_val_loss'])
    summary_path = os.path.join(cfg['LOG_DIR'], f"multi_seed_summary_{timestamp}.csv")
    fieldnames = ['seed', 'lambda', 'best_val_loss', 'best_val_acc',
                  'total_epochs', 'best_val_loss_epoch', 'run_log_dir', 'status']
    with open(summary_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    print(f"\n{'='*60}\n>>> 多 seed 训练完成，汇总 (按 best_val_loss 升序)\n{'='*60}")
    print(f"{'seed':>6} {'λ':>10} {'val_loss':>12} {'val_acc':>10} {'epochs':>7} {'status':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r['seed']:>6} {r['lambda']:>10.6f} {r['best_val_loss']:>12.6f} "
              f"{r['best_val_acc']:>10.6f} {r['total_epochs']:>7} {r['status']:>10}")
    print(f"\n汇总 CSV: {summary_path}")


if __name__ == "__main__":
    main()

