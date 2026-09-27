"""cnn 预测适配器（B03）：预测缓存四字段 → core Prediction 标准契约。

谱系（只读依据，不跑训练）：
- ``exp_ret`` 来自 ``scripts/eval_bins_mapping.py``：``(probs * centers52).sum(-1)``
  （``centers52 = linspace(-0.255, 0.255, 52)``，pure_reg 模式直接取回归头输出）；
- ``true_ret`` 口径为训练标签 ``future_ret``（``data/labels.py``）：
  ``open[t+1+horizon] / open[t+1] - 1``，``horizon = 5`` 与训练 ``HORIZON`` 一致；
- ``dates``/``codes`` 为逐样本对齐的信号归属日与标的代码。

隔离语义：
- 成交路径只消费本模块产出的 ``Prediction``（仅载 ``exp_ret``）；
  ``true_ret`` 仅经显式方法 ``actuals_for_cross_section`` 提供给截面评估，
  本模块不存在其它暴露 ``true_ret`` 的方法；
- 空截面返回空元组 + ``empty_cross_section_count``（不断整段区间评估）；
- ``NaN``/``inf`` 的 ``exp_ret`` 按原因计数后剔除，不静默丢弃。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from backtest_core.contracts import Prediction, PredictionType, RankingDirection
from backtest_core.contracts.validation import ensure_calendar_date, ensure_non_empty_str

from backtest.cnn_adapter.common import signal_time_for
from data.schema import validate_prediction_cache_arrays

__all__ = ["LABEL_FORMULA", "PREDICTED_HORIZON", "CnnPredictionAdapter", "PredictionCounters"]

# 与训练标签 horizon 一致并锁定（data.dataset 默认 HORIZON=5）：
# 改此常量即改谱系，单测锁定为 5（变异为 6 必须失败）。
PREDICTED_HORIZON = 5
# 标签公式谱系（data.labels._future_ret_open_open 口径，horizon=5）。
LABEL_FORMULA = "future_ret[t]=open[t+1+horizon]/open[t+1]-1,horizon=5"
# exp_ret 映射谱系（scripts/eval_bins_mapping.py 口径，可注入字段另见 provenance）。
EXP_RET_MAPPING = "exp_ret=(probs*centers52).sum(-1),centers52=linspace(-0.255,0.255,52)"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PredictionCounters:
    """计数快照：键名稳定，供 B05 provenance 消费；均为实例生命周期累计值。"""

    predicted_count: int = 0
    dropped_nan_count: int = 0
    dropped_inf_count: int = 0
    invalid_true_count: int = 0
    empty_cross_section_count: int = 0


class CnnPredictionAdapter:
    """预测缓存 → core Prediction（B03；成交路径仅消费本模块的 Prediction）。

    ``cache`` 为 ``load_prediction_cache`` 产出的四字段映射；
    谱系字段（模型名/检查点/轮次/BINS 版本/评估脚本版本）由调用方注入，
    经 ``provenance`` 原样透传，不硬编码。
    """

    def __init__(self, cache: Mapping, *, model_name: str, checkpoint: str,
                 bins_version: str, eval_script_version: str, epoch=None) -> None:
        ensure_non_empty_str(model_name, "model_name")
        ensure_non_empty_str(checkpoint, "checkpoint")
        ensure_non_empty_str(bins_version, "bins_version")
        ensure_non_empty_str(eval_script_version, "eval_script_version")
        if epoch is not None and not isinstance(epoch, (int, str)):
            raise TypeError(f"epoch must be an int, str or None, got {epoch!r}")
        validate_prediction_cache_arrays(dict(cache), "预测缓存")
        self._model_name = model_name
        self._checkpoint = checkpoint
        self._epoch = epoch
        self._bins_version = bins_version
        self._eval_script_version = eval_script_version
        self._run_id = checkpoint if epoch is None else f"{checkpoint}#epoch={epoch}"
        self._exp = np.asarray(cache["exp_ret"], dtype=np.float64)
        self._true = np.asarray(cache["true_ret"], dtype=np.float64)
        self._dates = tuple(pd.Timestamp(day).date() for day in np.asarray(cache["dates"]).tolist())
        self._codes = tuple(self._checked_code(code) for code in np.asarray(cache["codes"]).tolist())
        self._index = self._build_index(self._dates, self._codes)
        self._predicted_count = 0
        self._dropped_nan_count = 0
        self._dropped_inf_count = 0
        self._invalid_true_count = 0
        self._empty_cross_section_count = 0
        self._warned: set[str] = set()

    @staticmethod
    def _checked_code(value: object) -> str:
        """标的代码校验：非空 str（避免混入后破坏升序语义）。"""
        if not isinstance(value, str):
            raise TypeError(f"instrument code must be a string, got {value!r}")
        ensure_non_empty_str(value, "instrument code")
        return value

    @staticmethod
    def _build_index(dates: tuple, codes: tuple) -> dict:
        """逐样本下标 → 按日分组；同日同码重复显式失败（避免静默取舍）。"""
        index: dict[date, list[int]] = {}
        seen: set[tuple[date, str]] = set()
        for pos, (day, code) in enumerate(zip(dates, codes)):
            if (day, code) in seen:
                raise ValueError(f"预测缓存同日同码重复: {(day, code)!r}")
            seen.add((day, code))
            index.setdefault(day, []).append(pos)
        return index

    @property
    def provenance(self) -> dict[str, str]:
        """score 谱系透传：exp_ret 来源全部可注入字段 + 锁定的 horizon/公式。"""
        return {"model_name": self._model_name, "checkpoint": self._checkpoint,
                "epoch": "" if self._epoch is None else str(self._epoch),
                "bins_version": self._bins_version, "eval_script_version": self._eval_script_version,
                "horizon": str(PREDICTED_HORIZON), "label_formula": LABEL_FORMULA,
                "exp_ret_mapping": EXP_RET_MAPPING}

    @property
    def counters(self) -> PredictionCounters:
        """计数快照：产出数/各类剔除数/空截面数（键名稳定）。"""
        return PredictionCounters(predicted_count=self._predicted_count,
                                  dropped_nan_count=self._dropped_nan_count,
                                  dropped_inf_count=self._dropped_inf_count,
                                  invalid_true_count=self._invalid_true_count,
                                  empty_cross_section_count=self._empty_cross_section_count)

    @property
    def available_dates(self) -> tuple:
        """缓存覆盖的信号归属日（升序）。"""
        return tuple(sorted(self._index))

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）。"""
        counters = self.counters
        return {"predicted_count": str(counters.predicted_count),
                "dropped_nan_count": str(counters.dropped_nan_count),
                "dropped_inf_count": str(counters.dropped_inf_count),
                "invalid_true_count": str(counters.invalid_true_count),
                "empty_cross_section_count": str(counters.empty_cross_section_count)}

    def predictions_for_date(self, trading_date: date) -> tuple:
        """指定归属日的 Prediction 序列（按标的代码升序，仅载 exp_ret）。

        NaN/inf 的 exp_ret 按原因计数后剔除；空截面返回空元组并计数。
        本方法绝不读取 true_ret（成交路径隔离由单测锁定）。
        """
        ensure_calendar_date(trading_date, "trading_date")
        rows = self._index.get(trading_date)
        if not rows:
            self._empty_cross_section_count += 1
            self._warn_once("empty_cross_section",
                            f"空截面：缓存无该归属日样本，返回空序列（{trading_date.isoformat()}）")
            return ()
        signal_time = signal_time_for(trading_date)
        predictions = []
        for code, pos in sorted((self._codes[pos], pos) for pos in rows):
            value = self._finite_exp(pos, code)
            if value is None:
                continue
            predictions.append(Prediction(instrument_id=code, signal_time=signal_time, value=value,
                                          prediction_type=PredictionType.PREDICTED_RETURN,
                                          ranking_direction=RankingDirection.DESCENDING,
                                          model_id=self._model_name, run_id=self._run_id,
                                          predicted_horizon=PREDICTED_HORIZON))
        self._predicted_count += len(predictions)
        return tuple(predictions)

    def actuals_for_cross_section(self, trading_date: date) -> dict:
        """指定归属日的实际收益映射（仅供截面评估消费 actuals）。

        口径为训练标签 ``future_ret``（``LABEL_FORMULA``，horizon=5）；
        非有限 true_ret 按 ``invalid_true_count`` 计数后剔除。
        本方法是 true_ret 的唯一出口。
        """
        ensure_calendar_date(trading_date, "trading_date")
        actuals: dict[str, float] = {}
        for pos in self._index.get(trading_date, ()):
            try:
                value = float(self._true[pos])
            except (TypeError, ValueError, OverflowError):
                value = math.nan
            if not math.isfinite(value):
                self._invalid_true_count += 1
                self._warn_once(f"invalid_true:{self._codes[pos]}",
                                f"true_ret 非有限，已剔除并计入 invalid_true_count: {self._codes[pos]!r}")
                continue
            actuals[self._codes[pos]] = value
        return dict(sorted(actuals.items()))

    def _finite_exp(self, pos: int, code: str) -> float | None:
        """单样本 exp_ret 校验：NaN/inf 按原因计数后返回 None（调用方剔除）。"""
        try:
            value = float(self._exp[pos])
        except (TypeError, ValueError, OverflowError):
            value = math.nan
        if math.isnan(value):
            self._dropped_nan_count += 1
            self._warn_once(f"dropped_nan:{code}", f"exp_ret 为 NaN，已剔除并计入 dropped_nan_count: {code!r}")
            return None
        if math.isinf(value):
            self._dropped_inf_count += 1
            self._warn_once(f"dropped_inf:{code}", f"exp_ret 为 inf，已剔除并计入 dropped_inf_count: {code!r}")
            return None
        return value

    def _warn_once(self, key: str, message: str) -> None:
        """同类事件只告警一次（后续仅计数，避免长区间刷屏）。"""
        if key in self._warned:
            return
        self._warned.add(key)
        logger.warning(message)
