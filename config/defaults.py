"""训练入口共用的默认配置。"""

from copy import deepcopy

import numpy as np
import torch

DEFAULT_PARQUET = "data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet"
DEFAULT_BINS = (np.linspace(-25, 25, 51) / 100).tolist()

_BASE_CONFIG = {
    "DEVICE": "cuda" if torch.cuda.is_available() else "cpu",
    "PARQUET_PATH": DEFAULT_PARQUET, "BINS": DEFAULT_BINS,
    "SEQ_LEN": 60, "HORIZON": 5, "BATCH_SIZE": 256, "NUM_WORKERS": 4,
    "TRAIN_START": "2013-01-01", "TRAIN_END": "2025-06-30",
    "VAL_START": "2025-07-01", "VAL_END": "2025-12-31",
    "TEST_START": "2026-01-01", "TEST_END": None,
    "NORMALIZE": "per_code", "SCALER_PATH": "logs/scaler_per_code.pkl",
    "MAX_CODES": None, "MAX_WINDOWS_PER_CODE": None,
    "model": "CNNTransformer", "criterion": "EMDLoss",
    "EMLossConfig": {"p": 2, "label_smoothing": True, "smooth_eps": 0.1},
    "DUAL_HEAD": False, "PURE_REG": False, "LAMBDA_REG": 0.2,
    "HUBER_DELTA": 1.0, "scheduler": "ReduceLROnPlateau",
    "LEARNING_RATE": 1e-4, "WEIGHT_DECAY": 1e-5, "EPOCHS": 50,
    "PATIENCE": 10, "LOG_DIR": "./logs",
}

_BASE_CONFIG["CNNTransformerConfig"] = {
    "featurenum": 45, "seq_len": 60, "num_classes": 52,
    "cnn_out_channels": 128, "d_model": 256, "nhead": 8,
    "cnn_kernel_sizes": [1, 3, 5, 7, 10], "num_encoder_layers": 4,
    "dropout_rate": 0.3,
}


def make_default_config(*, dual_head: bool = False) -> dict:
    """返回不会与其他训练入口共享嵌套状态的默认配置。"""
    config = deepcopy(_BASE_CONFIG)
    config["DUAL_HEAD"] = dual_head
    config["num_classes"] = len(config["BINS"]) + 1
    config["CNNTransformerConfig"]["num_classes"] = config["num_classes"]
    config["CNNTransformerConfig"]["seq_len"] = config["SEQ_LEN"]
    return config
