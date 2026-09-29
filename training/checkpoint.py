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
from typing import Any

import numpy as np
import torch
from torch import nn, optim

logger = logging.getLogger(__name__)

MODEL_KEY = "model"
OPTIMIZER_KEY = "optimizer"
SCHEDULER_KEY = "scheduler"
CHECKPOINT_KEYS = (MODEL_KEY, OPTIMIZER_KEY, SCHEDULER_KEY, "epoch", "config")


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
    """存 dict 格式 checkpoint（含 optimizer/scheduler/epoch/config）。"""
    payload = {
        MODEL_KEY: model.state_dict(),
        OPTIMIZER_KEY: optimizer.state_dict() if optimizer is not None else None,
        SCHEDULER_KEY: scheduler.state_dict() if scheduler is not None else None,
        "epoch": epoch,
        "config": _json_safe_config(config),
    }
    torch.save(payload, path)


def load_checkpoint(path: str, map_location: Any = "cpu") -> Any:
    """读 checkpoint（新 dict / 旧裸 state_dict 均可）。

    ``weights_only`` 语义兼容：新 torch（≥2.6 默认 True）对纯张量 payload 安全；
    老版本无此参数时回退不传。dict 内仅含 state_dict/标量，无任意代码对象。
    """
    kwargs: dict = {"map_location": map_location}
    try:
        return torch.load(path, weights_only=True, **kwargs)
    except TypeError:  # 老 torch 无 weights_only 参数
        return torch.load(path, **kwargs)


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
