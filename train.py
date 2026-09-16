"""Parquet 直通训练入口：quant 最新因子数据 -> CNNTransformer -> EMDLoss

链路（per-code 共识）：
  data/test/train_data/train_data_v1_*.parquet (51 raw特征+18 G9 mask=F=69, 11M行, G6/G7已剔除)
    -> ParquetDataset (is_trading过滤, future_ret=open[t+6]/open[t+1]-1 52类, per-code分组归一化)
    -> CNNTransformer (featurenum=69, seq_len=60)
    -> EMDLoss (有序分类)
    -> Trainer (早停 + 调度)

使用：
  uv run --project . python train.py --max_codes 20 --epochs 2 --batch_size 256
  uv run --project . python train.py --train_start 2013-01-01 --train_end 2023-12-31 --val_start 2024-01-01 --val_end 2025-12-31

历史说明：旧 main2.py 的 NPZ 训练链路已删除；本脚本使用 parquet、F=69 和 future 5d open-open 标签。
F=45 仅代表旧特征/历史 checkpoint，不属于当前默认训练契约。
旧模型 checkpoint 不属于当前加载契约，历史结果仅供参考且不可与当前口径混用。
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
from data.dataset import ParquetDataConfig, ParquetDataset, _RollingDatasetState
from log_manager import LoggerManager
from training import Trainer
from training.factory import build_criterion, build_model, build_optimizer_scheduler
from visualization import Visualizer

config = make_default_config()


ROLLING_SCOPES = ("e2", "e3", "e4")


def set_all_seeds(seed: int):
    """设置所有随机种子，确保可复现（random/numpy/torch/cuda）。"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def configure_preprocessing(config: dict, normalize: str, rolling_scope: str = "e4") -> None:
    """Apply the explicit preprocessing choice and isolate its artifacts."""
    if normalize not in {"per_code", "rolling"}:
        raise ValueError(f"未知 normalize: {normalize}")
    config["NORMALIZE"] = normalize
    if normalize == "rolling":
        if rolling_scope not in ROLLING_SCOPES:
            raise ValueError(f"未知 rolling_scope: {rolling_scope!r}，仅支持 e2/e3/e4")
        config["ROLLING_SCOPE"] = rolling_scope
        config["SCALER_PATH"] = f"logs/rolling_{rolling_scope}/scaler_rolling_{rolling_scope}.pkl"
        config["LOG_DIR"] = f"./logs/rolling_{rolling_scope}"


def load_rolling_state(path: str, expected_scope: str | None = None) -> _RollingDatasetState:
    """加载 rolling preprocessing state，异 scope 直接拒绝（不做静默复用）。

    scope 校验复用 T02 `_RollingDatasetState.validate` 的 scope 参数语义：
    state 自带 scope 必须 == 请求 scope，否则抛 ValueError。
    """
    state = _RollingDatasetState.load(path)
    if expected_scope is not None and state.normalizer.config.scope != expected_scope:
        raise ValueError(
            f"rolling scope 不匹配：state={state.normalizer.config.scope!r} vs 请求={expected_scope!r}"
        )
    return state


def build_preprocessing_metadata(
    mode: str,
    preprocessing_state,
    feature_cols: list[str],
    featurenum: int,
    seq_len: int,
    num_classes: int,
    scope: str | None = None,
    seed: int | None = None,
) -> dict:
    """Build JSON-safe run metadata and reject incompatible model dimensions."""
    if featurenum != 69:
        raise ValueError(f"preprocessing metadata featurenum 不匹配: {featurenum}, expected 69")
    metadata: dict = {
        "mode": mode,
        "featurenum": featurenum,
        "seq_len": seq_len,
        "num_classes": num_classes,
        "feature_cols": list(feature_cols),
    }
    if seed is not None:
        metadata["seed"] = seed
    if mode == "rolling":
        if not isinstance(preprocessing_state, _RollingDatasetState):
            raise TypeError("rolling metadata 缺少 RollingDatasetState")
        if feature_cols != preprocessing_state.feature_cols:
            raise ValueError("rolling metadata feature schema 不匹配")
        state_scope = preprocessing_state.normalizer.config.scope
        if scope is not None and state_scope != scope:
            raise ValueError(f"rolling scope 不匹配：state={state_scope!r} vs 请求={scope!r}")
        metadata["scope"] = state_scope
        metadata["digest"] = preprocessing_state.normalizer.transform_config_digest()
        metadata["identity"] = preprocessing_state.identity_hash
        metadata["schema_manifest"] = preprocessing_state.schema_manifest
        metadata["schema_identity"] = preprocessing_state.identity_hash
    return metadata


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
    p.add_argument("--patience", type=int, default=config['PATIENCE'], help="早停耐心轮数")
    p.add_argument("--lr", type=float, default=config['LEARNING_RATE'])
    p.add_argument("--max_codes", type=int, default=None, help="调试：仅取前 N 只股票")
    p.add_argument("--max_windows_per_code", type=int, default=None)
    p.add_argument("--no_val", action="store_true", help="不使用验证集")
    p.add_argument("--smoke", action="store_true", help="冒烟测试：max_codes=20, epochs=1, batch 256")
    p.add_argument("--dual_head", action="store_true", help="双头回归：DualLoss=EMD+λHuber，默认关保 baseline")
    p.add_argument("--pure_reg", action="store_true", help="纯回归消融：仅 Huber(ret_pred)，分类头无梯度")
    p.add_argument("--lambda_reg", type=float, default=config['LAMBDA_REG'], help="双头回归项权重 λ")
    p.add_argument("--huber_delta", type=float, default=config['HUBER_DELTA'], help="Huber delta")
    p.add_argument("--normalize", choices=["per_code", "rolling"], default=config["NORMALIZE"])
    p.add_argument("--rolling_scope", choices=list(ROLLING_SCOPES), default=config["ROLLING_SCOPE"],
                   help="rolling 子集范围 e2/e3/e4（默认 e4=全量；非 rolling 时忽略）")
    p.add_argument("--seed", type=int, default=config["SEED"], help="全局随机种子（默认 42）")
    return p.parse_args()


def main():
    args = parse_args()
    # seed 必须在数据构建与模型初始化之前生效，保证 E1–E4 同一种子可复现
    set_all_seeds(args.seed)
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
    config['PATIENCE'] = args.patience
    config['LEARNING_RATE'] = args.lr
    config['MAX_CODES'] = args.max_codes
    config['MAX_WINDOWS_PER_CODE'] = args.max_windows_per_code
    config['DUAL_HEAD'] = args.dual_head
    config['PURE_REG'] = args.pure_reg
    config['LAMBDA_REG'] = args.lambda_reg
    config['HUBER_DELTA'] = args.huber_delta
    config['SEED'] = args.seed
    config['ROLLING_SCOPE'] = args.rolling_scope
    configure_preprocessing(config, args.normalize, args.rolling_scope)
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
        rolling_scope=config['ROLLING_SCOPE'],
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
    train_loader, val_loader, _scaler_stats = ParquetDataset.create_dataloaders(
        parquet_cfg,
        train_start=train_start,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        scaler_path=config['SCALER_PATH'],
    )
    train_dataset = cast(ParquetDataset, train_loader.dataset)
    dataset_scaler = train_dataset.scaler_stats
    if config["NORMALIZE"] == "rolling":
        if not isinstance(dataset_scaler, _RollingDatasetState):
            raise ValueError("rolling 数据集缺少有效 preprocessing identity")
        preprocessing_metadata = build_preprocessing_metadata(
            "rolling",
            dataset_scaler,
            train_dataset.feature_cols,
            train_dataset.num_features,
            config["SEQ_LEN"],
            config["CNNTransformerConfig"]["num_classes"],
            scope=config["ROLLING_SCOPE"],
            seed=config["SEED"],
        )
        preprocessing_metadata["rolling_audit"] = dict(train_dataset.rolling_audit)
    else:
        preprocessing_metadata = {
            "mode": "per_code",
            "seed": config.get("SEED"),
            "schema_manifest": getattr(dataset_scaler, "identity_manifest", None),
            "schema_identity": getattr(dataset_scaler, "identity_hash", None),
            "feature_cols": list(train_dataset.feature_cols),
            "featurenum": train_dataset.num_features,
            "seq_len": config["SEQ_LEN"],
            "num_classes": config["CNNTransformerConfig"]["num_classes"],
        }
    log_config["preprocessing"] = preprocessing_metadata
    config["preprocessing"] = preprocessing_metadata
    with open(os.path.join(config["run_log_dir"], "config.json"), "w", encoding="utf-8") as f:
        json.dump(log_config, f, indent=2, ensure_ascii=False)
    logger.info(f"训练集样本数: {len(train_dataset):,}")
    if val_loader is not None:
        val_dataset = cast(ParquetDataset, val_loader.dataset)
        logger.info(f"验证集样本数: {len(val_dataset):,}")
    # test 集日志（不入 Trainer，仅记录，待 2026 数据增量后可用）
    if test_start:
        logger.info(f"测试集预留: {test_start} ~ {test_end or '至今'} (当前 parquet 至 2025-12-31，暂为空)")

    # 校验 val 非空（新切分 2025下半年样本较少，smoke 20股可能仅 ~2k 窗口）
    if val_loader is not None and len(cast(ParquetDataset, val_loader.dataset)) == 0:
        logger.warning("验证集为空，请检查 VAL_START/VAL_END 与 max_codes 组合")

    # 自动校正 featurenum
    actual_featurenum = train_dataset.num_features
    if config["NORMALIZE"] == "rolling" and actual_featurenum != config["CNNTransformerConfig"]["featurenum"]:
        raise ValueError(
            "rolling preprocessing 与模型 featurenum 不匹配，拒绝加载旧/错误维度配置: "
            f"config={config['CNNTransformerConfig']['featurenum']} actual={actual_featurenum}"
        )
    if actual_featurenum != config["CNNTransformerConfig"]['featurenum']:
        logger.warning(f"特征数不匹配: config={config['CNNTransformerConfig']['featurenum']} vs 实际={actual_featurenum}，已自动校正")
        config["CNNTransformerConfig"]['featurenum'] = actual_featurenum
        log_config["CNNTransformerConfig"]['featurenum'] = actual_featurenum
        with open(os.path.join(config["run_log_dir"], "config.json"), "w") as f:
            json.dump(log_config, f, indent=2, ensure_ascii=False)
        logger.info(f"已重写 config.json: featurenum={actual_featurenum}")

    # 模型
    logger.info("=== 初始化模型 ===")
    model, model_cfg = build_model(config)
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"总参数量: {total_params:,}")
    logger.info(f"可训练参数量: {trainable_params:,}")
    logger.info(f"可训练比例: {100*trainable_params/total_params:.2f}%")
    # 打印输入维度校验
    logger.info(f"模型输入: [batch, featurenum={model_cfg.featurenum}, seq_len={model_cfg.seq_len}] -> {model_cfg.num_classes} 类")

    # 损失 & 优化器
    logger.info("=== 初始化损失与优化器 ===")
    criterion = build_criterion(config)
    if config['PURE_REG']:
        logger.info(f"纯回归 PureRegLoss: Huber(δ={config['HUBER_DELTA']})，分类头 logits 不参与损失（无梯度）")
    elif config['DUAL_HEAD']:
        logger.info(f"双头 DualLoss: EMD + λ={config['LAMBDA_REG']} Huber(δ={config['HUBER_DELTA']})")
    optimizer, scheduler = build_optimizer_scheduler(model, config)

    # 训练
    logger.info("=== 开始训练 ===")
    trainer = Trainer(
        model=model,
        config=config,
        train_loader=train_loader,
        val_loader=cast(torch.utils.data.DataLoader, val_loader),
        criterion=criterion,
        optimizer=optimizer,
        scheduler=cast(Any, scheduler),
    )
    try:
        trainer.train()
    except KeyboardInterrupt:
        logger.warning("训练被中断")

    # 可视化
    train_losses, _, train_accs, _ = trainer.get_training_history()
    try:
        vis_path = os.path.join(config["run_log_dir"], "training_curve.png")
        if val_loader is not None:
            _, val_losses, _, val_accs = trainer.get_training_history()
        else:
            val_losses, val_accs = [], []
        Visualizer.plot_training_curves(train_losses, val_losses, train_accs, val_accs, save_path=vis_path)
        logger.info(f"训练曲线已保存: {vis_path}")
    except (OSError, RuntimeError, TypeError, ValueError) as e:
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
