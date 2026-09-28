"""goal 预测适配器（C03）：pred parquet → core Prediction 标准契约。

三种 score 语义映射（列实证见下，单测逐项锁定）：
- score_raw：存盘 ``score`` 列原值。v2 模型在字面标签上训练
  （``SCORE_LABEL_FORMULA``，rank 与可实现收益单调递减），故原值不直接用，
  仅作谱系记录（provenance 记列名与取负公式）。
- score_trade = ``SCORE_TRADE_SIGN × score_raw``（即 -score）：交易用信号
  （STRATEGY §2 口径；metrics_v2 TEST 上 score vs 字面标签 IC +0.0764，
  取负后即 -score vs 可实现收益 +0.0764）→ ``Prediction.value``，
  类型 ``PREDICTED_RETURN``。
- score_rank：截面内按 score_trade 降序隐式排名，不单列字段、不另设类型。
  选 PREDICTED_RETURN 而非 RANKING_SCORE 的理由：截面评估对两者数值直接排序
  不做归一（``evaluation/cross_section.py``），而 score_trade 继承 HGB 回归量纲
  （收益单位小数）并锁定 horizon=5，PREDICTED_RETURN 保留可比口径语义；
  RANKING_SCORE 留给纯名次信号。

列实证（2026-09-11，pyarrow 只读列子集取样）：
- ``backtest/synth_*.parquet``（各 418,400 行）与
  ``artifacts/baseline/pred_test.parquet``（2,088,393 行）：5 列
  code/kline_time/score/future_ret_5d/q_true。
- ``artifacts/opt_model/pred_test_v2.parquet``（2,082,694 行）：上述 5 列 +
  ``realizable_ret``（字面训练标签列）；本适配器刻意不读该列——成交路径的
  标签隔离只留 ``future_ret_5d`` 唯一出口，多一列标签即多一条泄漏面。
- ``q_true`` 引擎未用仅兼容（``backtest/engine.py`` docstring），本适配器不读。
- 首截面符号实证：synth_good 首日 score vs future_ret_5d spearman +0.086；
  baseline 首日 +0.028；v2 首日 -0.120（字面标签倒置的符号证据，取负后 +0.120）。

隔离语义（仿 B03）：
- 成交路径只消费本模块产出的 ``Prediction``（仅载 score_trade）；
  ``future_ret_5d`` 唯一出口为 ``actuals_for_cross_section``（截面评估诊断用，
  引擎从 market 自算收益，不读它）；
- 空截面返回空元组 + ``empty_cross_section_count``（与 B03 一致：ValueError 会
  中断整段区间评估，空元组不断流）；
- NaN/inf 的 score 按原因计数后剔除，不静默丢弃。

谱系：模型/特征/标签口径/脚本版本由调用方注入，经 ``provenance`` 原样透传；
本模块禁 import torch、禁 import 模型 checkpoint（只传谱系字段，C04 验收）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts import Prediction, PredictionType, RankingDirection
from backtest_core.contracts.validation import (
    ensure_calendar_date,
    ensure_non_empty_str,
)

from goal_adapter.common import signal_time_for

__all__ = [
    "ACTUALS_LABEL_FORMULA",
    "PREDICTED_HORIZON",
    "SCORE_COL_RAW",
    "SCORE_LABEL_FORMULA",
    "SCORE_TRADE_FORMULA",
    "SCORE_TRADE_SIGN",
    "GoalPredictionAdapter",
    "PredictionCounters",
]

# 可实现收益 5 交易日口径锁定（T+1 open 买、5 个有效交易日后 open 卖；
# 字面标签 open[t+6]/open[t+1]-1 即 5 段收益；改此常量即改谱系）。
PREDICTED_HORIZON = 5
# 存盘 score 取负后使用（STRATEGY §2）；改符号即反转交易方向，单测锁定。
SCORE_TRADE_SIGN = -1.0
# 存盘原值列名（provenance 谱系记录，不直接消费）。
SCORE_COL_RAW = "score"
# 字面训练标签（models/train_realizable.py LABEL_FORMULA_LITERAL，rank 递减故取负）。
SCORE_LABEL_FORMULA = "open[t+1]/open[t+6]-1"
# 诊断对照标签（engine/截面口径，actuals 唯一出口承载）。
ACTUALS_LABEL_FORMULA = "future_ret_5d=close[t+5]/close[t]-1"
# 交易信号映射公式（provenance 锁定）。
SCORE_TRADE_FORMULA = "score_trade=-score"

# 只读必需 4 列：realizable_ret/q_true 刻意不读（见模块 docstring）。
_READ_COLS = ["code", "kline_time", "score", "future_ret_5d"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PredictionCounters:
    """计数快照：键名稳定，供 C05 provenance 消费；均为实例生命周期累计值."""

    predicted_count: int = 0
    dropped_nan_count: int = 0
    dropped_inf_count: int = 0
    invalid_true_count: int = 0
    empty_cross_section_count: int = 0


class GoalPredictionAdapter:
    """pred parquet → core Prediction（C03；成交路径仅消费本模块的 Prediction）。

    谱系字段（模型名/权重路径/特征版本/脚本版本）由调用方注入，经
    ``provenance`` 原样透传；权重路径仅为字符串血缘，不发生 import。
    """

    def __init__(
        self,
        pred_path: str,
        *,
        model_name: str,
        model_artifact: str,
        feature_version: str,
        script_version: str,
    ) -> None:
        ensure_non_empty_str(pred_path, "pred_path")
        ensure_non_empty_str(model_name, "model_name")
        ensure_non_empty_str(model_artifact, "model_artifact")
        ensure_non_empty_str(feature_version, "feature_version")
        ensure_non_empty_str(script_version, "script_version")
        self._model_name = model_name
        self._model_artifact = model_artifact
        self._feature_version = feature_version
        self._script_version = script_version
        self._run_id = f"{model_artifact}#{feature_version}"
        try:
            frame = pq.read_table(str(pred_path), columns=_READ_COLS).to_pandas()
        except (ValueError, OSError) as exc:
            raise ValueError(f"pred parquet 缺少必需列 {_READ_COLS} 或不可读：{exc}") from exc
        self._score, self._future, dates, codes = self._checked_columns(frame)
        self._dates = dates
        self._codes = codes
        self._index = self._build_index(dates, codes)
        self._predicted_count = 0
        self._dropped_nan_count = 0
        self._dropped_inf_count = 0
        self._invalid_true_count = 0
        self._empty_cross_section_count = 0
        self._warned: set[str] = set()

    @staticmethod
    def _checked_columns(frame: pd.DataFrame) -> tuple:
        """列校验：code 非空 str；kline_time 可解析（非法显式失败，不静默丢）；数值列 float 化."""
        codes = tuple("" if value is None else str(value) for value in frame["code"].tolist())
        for code in codes:
            ensure_non_empty_str(code, "code")
        times = pd.to_datetime(frame["kline_time"], errors="coerce")
        if bool(times.isna().any()):
            raise ValueError("pred parquet 含不可解析的 kline_time")
        dates = tuple(pd.Timestamp(day).date() for day in times.tolist())
        score = np.asarray(pd.to_numeric(frame["score"], errors="coerce"), dtype=np.float64)
        future = np.asarray(pd.to_numeric(frame["future_ret_5d"], errors="coerce"), dtype=np.float64)
        return score, future, dates, codes

    @staticmethod
    def _build_index(dates: tuple, codes: tuple) -> dict:
        """逐样本下标 → 按日分组；同日同码重复显式失败（避免静默取舍）。"""
        index: dict[date, list[int]] = {}
        seen: set[tuple[date, str]] = set()
        for pos, (day, code) in enumerate(zip(dates, codes)):
            if (day, code) in seen:
                raise ValueError(f"pred parquet 同日同码重复：{(day, code)!r}")
            seen.add((day, code))
            index.setdefault(day, []).append(pos)
        return index

    @property
    def provenance(self) -> dict[str, str]:
        """谱系透传：全部可注入字段 + 锁定的 horizon/标签公式/映射公式."""
        return {
            "model_name": self._model_name,
            "model_artifact": self._model_artifact,
            "feature_version": self._feature_version,
            "script_version": self._script_version,
            "horizon": str(PREDICTED_HORIZON),
            "score_label_formula": SCORE_LABEL_FORMULA,
            "actuals_label_formula": ACTUALS_LABEL_FORMULA,
            "score_mapping": SCORE_TRADE_FORMULA,
            "score_raw_column": SCORE_COL_RAW,
        }

    @property
    def counters(self) -> PredictionCounters:
        """计数快照：产出数/各类剔除数/空截面数（键名稳定）。"""
        return PredictionCounters(
            predicted_count=self._predicted_count,
            dropped_nan_count=self._dropped_nan_count,
            dropped_inf_count=self._dropped_inf_count,
            invalid_true_count=self._invalid_true_count,
            empty_cross_section_count=self._empty_cross_section_count,
        )

    @property
    def available_dates(self) -> tuple:
        """pred 覆盖的信号归属日（升序）。"""
        return tuple(sorted(self._index))

    def warnings_summary(self) -> dict[str, str]:
        """字符串化计数摘要（值一律 str，便于 manifest 落盘）。"""
        counters = self.counters
        return {
            "predicted_count": str(counters.predicted_count),
            "dropped_nan_count": str(counters.dropped_nan_count),
            "dropped_inf_count": str(counters.dropped_inf_count),
            "invalid_true_count": str(counters.invalid_true_count),
            "empty_cross_section_count": str(counters.empty_cross_section_count),
        }

    def predictions_for_date(self, trading_date: date) -> tuple:
        """指定归属日的 Prediction 序列（按标的代码升序，仅载 score_trade）。

        NaN/inf 的 score 按原因计数后剔除；空截面返回空元组并计数。
        本方法绝不读取 future_ret_5d（成交路径隔离由单测源码扫描锁定）。
        """
        ensure_calendar_date(trading_date, "trading_date")
        rows = self._index.get(trading_date)
        if not rows:
            self._empty_cross_section_count += 1
            self._warn_once(
                "empty_cross_section",
                f"空截面：pred 无该归属日样本，返回空序列（{trading_date.isoformat()}）",
            )
            return ()
        signal_time = signal_time_for(trading_date)
        predictions = []
        for code, pos in sorted((self._codes[pos], pos) for pos in rows):
            value = self._finite_trade(pos, code)
            if value is None:
                continue
            predictions.append(
                Prediction(
                    instrument_id=code,
                    signal_time=signal_time,
                    value=value,
                    prediction_type=PredictionType.PREDICTED_RETURN,
                    ranking_direction=RankingDirection.DESCENDING,
                    model_id=self._model_name,
                    run_id=self._run_id,
                    predicted_horizon=PREDICTED_HORIZON,
                )
            )
        self._predicted_count += len(predictions)
        return tuple(predictions)

    def actuals_for_cross_section(self, trading_date: date) -> dict:
        """指定归属日的实际收益映射（future_ret_5d 标签的唯一出口，仅供截面评估诊断）。

        非有限 future_ret_5d 按 ``invalid_true_count`` 计数后剔除。
        本方法绝不构造 Prediction（诊断路径隔离由单测源码扫描锁定）。
        """
        ensure_calendar_date(trading_date, "trading_date")
        actuals: dict[str, float] = {}
        for pos in self._index.get(trading_date, ()):
            try:
                value = float(self._future[pos])
            except (TypeError, ValueError, OverflowError):
                value = math.nan
            if not math.isfinite(value):
                self._invalid_true_count += 1
                self._warn_once(
                    f"invalid_true:{self._codes[pos]}",
                    f"future_ret_5d 非有限，已剔除并计入 invalid_true_count：{self._codes[pos]!r}",
                )
                continue
            actuals[self._codes[pos]] = value
        return dict(sorted(actuals.items()))

    def _finite_trade(self, pos: int, code: str) -> float | None:
        """存盘 score → score_trade：NaN/inf 按原因计数后返回 None（调用方剔除）。"""
        try:
            raw = float(self._score[pos])
        except (TypeError, ValueError, OverflowError):
            raw = math.nan
        if math.isnan(raw):
            self._dropped_nan_count += 1
            self._warn_once(f"dropped_nan:{code}", f"score 为 NaN，已剔除并计入 dropped_nan_count：{code!r}")
            return None
        if math.isinf(raw):
            self._dropped_inf_count += 1
            self._warn_once(f"dropped_inf:{code}", f"score 为 inf，已剔除并计入 dropped_inf_count：{code!r}")
            return None
        return SCORE_TRADE_SIGN * raw

    def _warn_once(self, key: str, message: str) -> None:
        """同类事件只告警一次（后续仅计数，避免长区间刷屏）。"""
        if key in self._warned:
            return
        self._warned.add(key)
        logger.warning(message)
