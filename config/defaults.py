"""训练入口共用的默认配置。"""

import sys
from copy import deepcopy

import numpy as np
import torch

if sys.platform == "win32":
    _DEFAULT_PARQUET = "Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"
else:
    _DEFAULT_PARQUET = "data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet"

DEFAULT_PARQUET = _DEFAULT_PARQUET
DEFAULT_BINS = (np.linspace(-38, 38, 51) / 100).tolist()


def bins_to_centers(bins) -> list:
    """由 BINS 边界派生 52 类中心（T09 方案A，唯一事实源）。

    语义：51 个边界对应 52 类（``np.digitize`` 口径）——内部 50 个为相邻边界
    中点，两尾各外推半步（首步/尾步的一半），共 52 中心。
    确定性纯函数：同输入恒返同输出（json 可序列化 list），无随机/全局状态。

    方案A漂移声明（用户已确认允许一次可解释漂移）：旧 eval 硬编码
    ``CENTERS52=linspace(-0.255,0.255,52)``（步长 0.01）与训练 BINS
    ``linspace(-0.38,0.38,51)``（步长 0.0152）不一致，属口径断裂。新中心为
    ``linspace(-0.3876,0.3876,52)``（步长 0.0152），即旧向量精确 1.52 倍线性
    缩放（BINS 边界比 0.38/0.255≈1.49，中心比 0.3876/0.255=1.52；任务描述
    ~1.49 为边界口径近似值）。排序不变，仅 exp_ret 绝对阈值需重审。
    """
    edges = np.asarray(bins, dtype=np.float64).ravel()
    if edges.size < 2:
        raise ValueError(f"BINS 至少需要 2 个边界，实际 {edges.size}")
    if not bool(np.all(np.diff(edges) > 0)):
        raise ValueError("BINS 必须严格递增")
    mids = ((edges[:-1] + edges[1:]) / 2.0).tolist()
    first_half = float(edges[1] - edges[0]) / 2.0
    last_half = float(edges[-1] - edges[-2]) / 2.0
    return [float(edges[0]) - first_half] + [float(v) for v in mids] + [float(edges[-1]) + last_half]


DEFAULT_CENTERS = bins_to_centers(DEFAULT_BINS)

# 生产实盘费率镜像（T09 集中；唯一事实源见 backtest/cnn_adapter/common.py
# UNIFIED_*：佣万2双边 min5 + 印花卖万5 + 过户万1双边；此处字面镜像供 config
# 侧引用，config 不反向 import backtest 以守模块边界。旧 backtest/engine.py
# 冻结值佣万2.5/印花万2.5/无过户费保持不动，不做任何修正。）
DEFAULT_BUY_RATE = 0.0002
DEFAULT_SELL_RATE = 0.0002
DEFAULT_STAMP_RATE = 0.0005
DEFAULT_TRANSFER_RATE = 0.00001
DEFAULT_MIN_COMMISSION = 5.0
DEFAULT_FEES: dict = {"commission_rate_buy": DEFAULT_BUY_RATE,
                      "commission_rate_sell": DEFAULT_SELL_RATE,
                      "min_commission": DEFAULT_MIN_COMMISSION,
                      "stamp_tax_rate": DEFAULT_STAMP_RATE,
                      "transfer_fee_rate": DEFAULT_TRANSFER_RATE}

# 键名大小写混用立约（T09：只立约不改值）：“model/criterion/scheduler”
# 等小写键与 “CNNTransformerConfig/EMLossConfig/DUAL_HEAD” 等大写键并存属历史
# checkpoint 兼容约束，重命名即断旧 ckpt config.json，禁止改值；新键一律大写。

_BASE_CONFIG = {
    "DEVICE": "cuda" if torch.cuda.is_available() else "cpu",
    "PARQUET_PATH": DEFAULT_PARQUET, "BINS": DEFAULT_BINS, "CENTERS": DEFAULT_CENTERS,
    "SEQ_LEN": 60, "HORIZON": 10, "BATCH_SIZE": 256, "NUM_WORKERS": 4,
    "TRAIN_START": "2013-01-01", "TRAIN_END": "2025-06-30",
    "VAL_START": "2025-07-01", "VAL_END": "2025-12-31",
    "TEST_START": "2026-01-01", "TEST_END": None,
    "NORMALIZE": "relative", "SCALER_PATH": None,
    "ROLLING_SCOPE": "e5", "SEED": 42,
    "LABEL_MODE": "absolute",  # absolute=原始 future_ret；excess=截面超额收益
    "CS_RANK": False,  # True=追加逐日全市场截面 rank 特征（旁路归一化）；默认关
    "CS_RANK_FEATURES": None,  # None=用 data/schema.DEFAULT_CS_RANK_FEATURES（16 个独立特征）
    "MKT_FACTORS": False,  # True=追加全市场截面因子（每日广播，旁路归一化）；默认关
    "MKT_FACTOR_LIST": None,  # None=用 data/schema.DEFAULT_MKT_FACTOR_FEATURES（11 个因子）
    "MAX_CODES": None, "MAX_WINDOWS_PER_CODE": None,
    "model": "CNNTransformer", "criterion": "EMDLoss",
    "EMLossConfig": {"p": 2, "label_smoothing": True, "smooth_eps": 0.1},
    "DUAL_HEAD": False, "PURE_REG": False, "LAMBDA_REG": 0.2,
    "HUBER_DELTA": 1.0, "scheduler": "ReduceLROnPlateau",
    "LEARNING_RATE": 3e-4, "WEIGHT_DECAY": 1e-5, "EPOCHS": 50,
    "PATIENCE": 10, "LOG_DIR": "./logs",
    "CACHE_ENABLED": True, "CACHE_DIR": None, "REBUILD_CACHE": False,
}

_BASE_CONFIG["CNNTransformerConfig"] = {
    "featurenum": 53, "seq_len": 60, "num_classes": 52,
    "cnn_out_channels": 128, "d_model": 256, "nhead": 8,
    "cnn_kernel_sizes": [1, 3, 5, 7, 10], "num_encoder_layers": 4,
    "dropout_rate": 0.3,
}


def make_default_config(*, dual_head: bool = False) -> dict:
    """返回不会与其他训练入口共享嵌套状态的默认配置。"""
    config = deepcopy(_BASE_CONFIG)
    config["DUAL_HEAD"] = dual_head
    config["CENTERS"] = bins_to_centers(config["BINS"])
    config["num_classes"] = len(config["BINS"]) + 1
    assert len(config["CENTERS"]) == config["num_classes"]  # T09：BINS→CENTERS→类别数链路
    config["CNNTransformerConfig"]["num_classes"] = config["num_classes"]
    config["CNNTransformerConfig"]["seq_len"] = config["SEQ_LEN"]
    return config
