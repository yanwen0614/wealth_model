"""训练组件工厂，集中维护入口间的构建规则。"""

import torch

from criterion.dual_loss import DualLoss
from criterion.emd_loss import EMDLoss
from criterion.pure_reg_loss import PureRegLoss
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer


def build_model(config: dict, actual_featurenum: int | None = None):
    """按配置构建模型，并在数据集提供维度时校正输入特征数。"""
    model_cfg_dict = dict(config["CNNTransformerConfig"])
    if actual_featurenum is not None:
        model_cfg_dict["featurenum"] = actual_featurenum
    model_cfg = ModelConfig(**model_cfg_dict)
    return CNNTransformer(model_cfg).to(config["DEVICE"]), model_cfg


def build_criterion(config: dict, *, lambda_reg: float | None = None):
    """构建纯分类、双头或纯回归损失。"""
    if config["PURE_REG"]:
        return PureRegLoss(num_classes=config["num_classes"], huber_delta=config["HUBER_DELTA"])
    if config["DUAL_HEAD"]:
        return DualLoss(
            num_classes=config["num_classes"], **config["EMLossConfig"],
            lambda_reg=config["LAMBDA_REG"] if lambda_reg is None else lambda_reg,
            huber_delta=config["HUBER_DELTA"],
        )
    return EMDLoss(num_classes=config["num_classes"], **config["EMLossConfig"])


def build_optimizer_scheduler(model, config: dict):
    """构建优化器和 Trainer 兼容的调度器。"""
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config["LEARNING_RATE"], weight_decay=config["WEIGHT_DECAY"]
    )
    if config["scheduler"] == "CosineAnnealingWarmRestarts":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
            optimizer, T_0=10, T_mult=2, eta_min=1e-6
        )
    else:
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5
        )
    return optimizer, scheduler
