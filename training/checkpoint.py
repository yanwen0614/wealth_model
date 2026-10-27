"""Checkpoint 单事实源（T14）：dict 格式 + 旧裸 state_dict 兼容加载。

新格式（best_model.pth）::
    {"model": state_dict, "optimizer": state_dict|None, "scheduler": state_dict|None,
     "epoch": int|None, "config": json-safe dict}

旧格式（裸 ``model.state_dict()``）加载侧经 :func:`extract_state_dict` 兼容，
评估脚本/训练恢复统一走本模块，不再直调 ``torch.load`` + ``load_state_dict``。
"""

import json
import logging
import warnings
from contextlib import contextmanager
from typing import Any, cast

import numpy as np
import torch
from torch import nn, optim

logger = logging.getLogger(__name__)

MODEL_KEY = "model"
OPTIMIZER_KEY = "optimizer"
SCHEDULER_KEY = "scheduler"
CHECKPOINT_KEYS = (MODEL_KEY, OPTIMIZER_KEY, SCHEDULER_KEY, "epoch", "config")

# 受限 allowlist：仅覆盖 torch.save 序列化 NumPy 标量（如 scheduler 步进后写入
# optimizer.param_groups[*].lr 的 numpy.float64）所必需的解码全局对象。
# NumPy 2.x 使用 numpy._core.multiarray，保留 numpy 1.x 导入路径兼容；项目依赖
# 下限为 NumPy 2.4。未知对象仍被 weights_only 拒绝。
def _numpy_multiarray_scalar():
    try:
        from numpy._core import multiarray  # numpy>=2
    except ImportError:
        from numpy.core import multiarray  # numpy<2
    return multiarray.scalar


_NUMPY_SAFE_GLOBALS = tuple(g for g in (
    _numpy_multiarray_scalar(),
    np.dtype,
    type(np.dtype(np.float64)),
))


@contextmanager
def _numpy_safe_globals():
    """受限放行 NumPy 标量解码全局对象（weights_only 语义下其余仍拒绝）。"""
    if not _NUMPY_SAFE_GLOBALS or not hasattr(torch.serialization, "safe_globals"):
        raise RuntimeError("checkpoint 安全兼容要求 PyTorch >= 2.6（weights_only + safe_globals）")
    with torch.serialization.safe_globals(cast(Any, list(_NUMPY_SAFE_GLOBALS))):
        yield


def _native_scalars(obj: Any) -> Any:
    """递归把 NumPy 标量转 Python 标量，新保存的 checkpoint 不再携带 numpy 全局对象。"""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {key: _native_scalars(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_native_scalars(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_native_scalars(value) for value in obj)
    return obj


def is_checkpoint_dict(obj: Any) -> bool:
    """新格式 dict（含 model 键）vs 旧裸 state_dict 判别。"""
    return isinstance(obj, dict) and MODEL_KEY in obj


def _json_safe_config(config: dict | None) -> dict:
    """沿 train.py 约束：ndarray→list，其余必须 json 可序列化。"""
    safe: dict = {}
    for k, v in (config or {}).items():
        if isinstance(v, np.ndarray):
            v = v.tolist()
        try:
            json.dumps({k: v})
        except (TypeError, ValueError) as e:
            raise ValueError(f"checkpoint config 不可 json 序列化: key={k!r} ({e})") from e
        safe[k] = v
    return safe


def save_checkpoint(path: str, model: nn.Module,
                    optimizer: optim.Optimizer | None = None,
                    scheduler: Any | None = None,
                    epoch: int | None = None,
                    config: dict | None = None) -> None:
    """存 dict 格式 checkpoint（含 optimizer/scheduler/epoch/config）。

    optimizer/scheduler state 中的 NumPy 标量（lr 等）原生化为 Python 标量，
    新保存文件不再依赖 NumPy 解码全局对象。
    """
    payload = {
        MODEL_KEY: model.state_dict(),
        OPTIMIZER_KEY: _native_scalars(optimizer.state_dict()) if optimizer is not None else None,
        SCHEDULER_KEY: _native_scalars(scheduler.state_dict()) if scheduler is not None else None,
        "epoch": epoch,
        "config": _json_safe_config(config),
    }
    torch.save(payload, path)


def load_checkpoint(path: str, map_location: Any = "cpu") -> Any:
    """读 checkpoint（新 dict / 旧裸 state_dict 均可）。

    ``weights_only`` 语义兼容：新 torch（≥2.6 默认 True）对纯张量 payload 安全；
    仅支持 PyTorch >=2.6。历史文件 optimizer 内的 NumPy 标量经受限
    allowlist（仅 :data:`_NUMPY_SAFE_GLOBALS`）放行，其余未知对象仍被拒绝。
    """
    kwargs: dict = {"map_location": map_location}
    with _numpy_safe_globals():
        return torch.load(path, weights_only=True, **kwargs)


def extract_state_dict(obj: Any) -> Any:
    """取模型 state_dict：新 dict 取 ['model']，旧裸 dict 原样返回（+ warning）。"""
    if is_checkpoint_dict(obj):
        return obj[MODEL_KEY]
    warnings.warn("加载旧格式裸 state_dict checkpoint（无 optimizer/scheduler/epoch），仅可评估不可续训",
                  UserWarning, stacklevel=3)
    return obj


def load_model_state(path: str, model: nn.Module, map_location: Any = "cpu",
                     strict: bool = True) -> dict:
    """评估/恢复统一入口：兼容加载 + 装入 model，返回 checkpoint 元信息。"""
    obj = load_checkpoint(path, map_location=map_location)
    model.load_state_dict(extract_state_dict(obj), strict=strict)
    if is_checkpoint_dict(obj):
        return {"epoch": obj.get("epoch"), "config": obj.get("config", {}),
                "has_optimizer": obj.get(OPTIMIZER_KEY) is not None,
                "has_scheduler": obj.get(SCHEDULER_KEY) is not None}
    return {"epoch": None, "config": {}, "has_optimizer": False, "has_scheduler": False}
