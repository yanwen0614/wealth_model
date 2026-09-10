"""让 unittest discover 不遮蔽项目 training 包。"""
from importlib import import_module
from pathlib import Path

__path__.append(str(Path(__file__).resolve().parents[3] / "training"))

EarlyStopping = import_module("training.early_stopping").EarlyStopping
Trainer = import_module("training.trainer").Trainer

__all__ = ["EarlyStopping", "Trainer"]
