"""散户友好模型配置类。"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class RetailModelConfig:
    """散户友好模型的超参数配置。

    设计原则：
    - 复用 CNN+Transformer 骨架（与 CNNTransformer 共享 MultiWindowInceptionCNN / TransformerEncoder）
    - 输出改为二分类概率（sigmoid）+ 可选回归辅助头
    - 损失函数面向高精度（precision ≥ 75%）优化

    默认值与 CNNTransformer 对齐（F=53, seq=60, d_model=256, nhead=8, layers=4）。
    """

    # ── 输入维度 ──
    featurenum: int = 53       # 特征数（数据集实测派生后覆盖）
    seq_len: int = 60          # 时间窗口长度

    # ── CNN 多尺度特征提取 ──
    cnn_out_channels: int = 128
    cnn_kernel_sizes: List[int] = field(default_factory=lambda: [1, 3, 5, 7, 10])

    # ── Transformer 长程依赖建模 ──
    d_model: int = 256
    nhead: int = 8
    num_encoder_layers: int = 4
    dropout_rate: float = 0.3

    # ── 损失函数（默认 BCEWithLogits + pos_weight） ──
    pos_weight: float = 2.0          # 正类损失权重（>1 → FP 惩罚更大 → 更高 precision）
                                     # pos_weight=2.0 时平衡数据 equilibrium p≈0.667
    lambda_reg: float = 0.3          # 回归辅助损失权重（引导特征学习）
    huber_delta: float = 1.0         # Huber loss delta
    # 以下为 ASL 遗留参数（当前版本弃用，仅保留接口兼容）
    gamma_pos: float = 0.0
    gamma_neg: float = 2.0

    # ── 推理决策 ──
    default_threshold: float = 0.65  # 默认决策阈值（训练后由 validate 校准覆盖）
    alpha_score: float = 0.5         # 综合评分 = α * p_bin + (1-α) * norm(ret_pred)（兼顾胜率与涨幅）


@dataclass
class RetailInferenceConfig:
    """散户模型推理配置（与预测缓存配套）。"""
    threshold: float = 0.65          # 决策阈值
    max_picks_per_day: int = 100     # 每日最大推荐标的（散户上限）
    min_picks_for_winrate: int = 3   # 计算日胜率所需最小标的数
