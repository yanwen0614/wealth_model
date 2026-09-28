"""goal_adapter.predictions 单测（C03）：unittest.TestCase 风格，双运行器兼容。

零触网；合成 pred parquet 走 tempfile（列对齐实证 schema 子集）；
真实 pred parquet 只读列子集小样本（文件缺失显式 skip）；goal 无 DB。
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow.parquet as pq
from backtest_core.contracts.enums import PredictionType, RankingDirection

from goal_adapter.predictions import (
    ACTUALS_LABEL_FORMULA,
    PREDICTED_HORIZON,
    SCORE_LABEL_FORMULA,
    SCORE_TRADE_SIGN,
    GoalPredictionAdapter,
)

COLS = ["code", "kline_time", "score", "future_ret_5d", "q_true"]


def _frame(rows):
    """合成行 → DataFrame（列对齐实证 schema；kline_time 为 datetime）。"""
    df = pd.DataFrame(rows, columns=COLS)
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    return df


def _write(path, df):
    df.to_parquet(path, index=False)


def _row(code, day, score, future_ret, q_true=2):
    return (code, day, score, future_ret, q_true)


def _adapter(path, **kwargs):
    """默认谱系注入（调用方透传，不硬编码权重路径）。"""
    params = {
        "model_name": "hgb-realizable-v2",
        "model_artifact": "artifacts/opt_model/model_hgb_v2.pkl",
        "feature_version": "feat49-train2013-2021",
        "script_version": "train_realizable.py@HEAD",
    }
    params.update(kwargs)
    return GoalPredictionAdapter(str(path), **params)


def _code_tokens(obj):
    """对象源码的代码 token 拼接（剔除注释/字符串/docstring，只留代码层引用）。"""
    import inspect
    import io
    import tokenize

    skip = (tokenize.COMMENT, tokenize.STRING, tokenize.NL, tokenize.NEWLINE,
            tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER)
    tokens = [tok.string for tok in tokenize.generate_tokens(io.StringIO(inspect.getsource(obj)).readline)
              if tok.type not in skip]
    return " ".join(tokens)


class ScoreMappingTests(unittest.TestCase):
    def test_trade_value_is_negated_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([
                _row("000001.SZ", "2024-04-02", 0.02, 0.01),
                _row("000002.SZ", "2024-04-02", -0.03, -0.02),
            ]))
            adapter = _adapter(path)
            preds = {p.instrument_id: p.value for p in adapter.predictions_for_date(date(2024, 4, 2))}
            # 存盘 score 取负后使用（STRATEGY §2：-score 为可执行方向）
            self.assertAlmostEqual(preds["000001.SZ"], -0.02)
            self.assertAlmostEqual(preds["000002.SZ"], 0.03)

    def test_prediction_type_direction_horizon_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            adapter = _adapter(path)
            (pred,) = adapter.predictions_for_date(date(2024, 4, 2))
            # score_trade 继承回归量纲（收益单位）故用 PREDICTED_RETURN，见模块 docstring
            self.assertEqual(pred.prediction_type, PredictionType.PREDICTED_RETURN)
            self.assertEqual(pred.ranking_direction, RankingDirection.DESCENDING)
            self.assertEqual(pred.predicted_horizon, PREDICTED_HORIZON)
            self.assertEqual(PREDICTED_HORIZON, 5)

    def test_signal_time_is_t1_shanghai_1500(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            adapter = _adapter(path)
            (pred,) = adapter.predictions_for_date(date(2024, 4, 2))
            # 收盘信号时点：当日 15:00 Asia/Shanghai（复用 C01 signal_time_for）
            self.assertEqual((pred.signal_time.hour, pred.signal_time.minute), (15, 0))
            self.assertEqual(str(pred.signal_time.tzinfo), "Asia/Shanghai")

    def test_mapping_constants_locked(self):
        # 映射关系常量锁定：改符号/公式即改谱系，单测逐项锁定
        self.assertEqual(SCORE_TRADE_SIGN, -1.0)
        self.assertEqual(SCORE_LABEL_FORMULA, "open[t+1]/open[t+6]-1")
        self.assertEqual(ACTUALS_LABEL_FORMULA, "future_ret_5d=close[t+5]/close[t]-1")

    def test_rank_order_matches_descending_trade_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([
                _row("000001.SZ", "2024-04-02", 0.05, 0.0),
                _row("000002.SZ", "2024-04-02", -0.01, 0.0),
                _row("000003.SZ", "2024-04-02", 0.02, 0.0),
            ]))
            adapter = _adapter(path)
            preds = adapter.predictions_for_date(date(2024, 4, 2))
            # score_rank 隐式表达：按 score_trade 降序即按 score_raw 升序
            ordered = sorted(preds, key=lambda p: p.value, reverse=True)
            self.assertEqual([p.instrument_id for p in ordered],
                             ["000002.SZ", "000003.SZ", "000001.SZ"])
            # 输出按代码升序（与 B03 一致，顺序与构造无关）
            self.assertEqual([p.instrument_id for p in preds],
                             ["000001.SZ", "000002.SZ", "000003.SZ"])


class LabelIsolationTests(unittest.TestCase):
    def test_predictions_immune_to_label_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            before = [p.value for p in _adapter(path).predictions_for_date(date(2024, 4, 2))]
            mutated = Path(tmp) / "mut.parquet"
            _write(mutated, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.99)]))
            after = [p.value for p in _adapter(mutated).predictions_for_date(date(2024, 4, 2))]
            # 标签混入预测：篡改 future_ret_5d 不得影响成交路径输出
            self.assertEqual(before, after)

    def test_actuals_immune_to_score_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            before = _adapter(path).actuals_for_cross_section(date(2024, 4, 2))
            mutated = Path(tmp) / "mut.parquet"
            _write(mutated, _frame([_row("000001.SZ", "2024-04-02", 0.99, 0.01)]))
            after = _adapter(mutated).actuals_for_cross_section(date(2024, 4, 2))
            # 预测混入诊断：篡改 score 不得影响标签出口
            self.assertEqual(before, after)
            self.assertAlmostEqual(after["000001.SZ"], 0.01)

    def test_source_scan_locks_isolation(self):
        import goal_adapter.predictions as module

        # 成交路径代码层不得出现标签列名；诊断路径代码层不得构造 Prediction；
        # 适配器只读 4 列：realizable_ret/q_true 无数据流（docstring 提及不计，
        # 只扫描代码 token，注释/字符串剔除）。
        self.assertNotIn("future_ret_5d", _code_tokens(module.GoalPredictionAdapter.predictions_for_date))
        self.assertNotIn("Prediction(", _code_tokens(module.GoalPredictionAdapter.actuals_for_cross_section))
        module_code = _code_tokens(module)
        self.assertNotIn("realizable_ret", module_code)
        self.assertNotIn("q_true", module_code)


class DegradedValueTests(unittest.TestCase):
    def test_nan_inf_scores_dropped_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([
                _row("000001.SZ", "2024-04-02", float("nan"), 0.01),
                _row("000002.SZ", "2024-04-02", float("inf"), 0.02),
                _row("000003.SZ", "2024-04-02", 0.04, 0.03),
            ]))
            adapter = _adapter(path)
            preds = adapter.predictions_for_date(date(2024, 4, 2))
            self.assertEqual([p.instrument_id for p in preds], ["000003.SZ"])
            self.assertAlmostEqual(preds[0].value, -0.04)
            counters = adapter.counters
            self.assertEqual(counters.dropped_nan_count, 1)
            self.assertEqual(counters.dropped_inf_count, 1)
            self.assertEqual(counters.predicted_count, 1)

    def test_empty_cross_section_returns_empty_tuple_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            adapter = _adapter(path)
            # 与 B03 一致选空元组+计数：ValueError 会中断整段区间评估
            self.assertEqual(adapter.predictions_for_date(date(2024, 4, 3)), ())
            self.assertEqual(adapter.counters.empty_cross_section_count, 1)

    def test_invalid_true_counted_and_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([
                _row("000001.SZ", "2024-04-02", 0.02, float("nan")),
                _row("000002.SZ", "2024-04-02", 0.03, 0.05),
            ]))
            adapter = _adapter(path)
            actuals = adapter.actuals_for_cross_section(date(2024, 4, 2))
            self.assertEqual(list(actuals), ["000002.SZ"])
            self.assertEqual(adapter.counters.invalid_true_count, 1)


class ProvenanceTests(unittest.TestCase):
    def test_provenance_pass_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([_row("000001.SZ", "2024-04-02", 0.02, 0.01)]))
            adapter = _adapter(path)
            provenance = adapter.provenance
            self.assertEqual(provenance["model_name"], "hgb-realizable-v2")
            self.assertEqual(provenance["feature_version"], "feat49-train2013-2021")
            self.assertEqual(provenance["horizon"], "5")
            self.assertEqual(provenance["score_mapping"], "score_trade=-score")
            (pred,) = adapter.predictions_for_date(date(2024, 4, 2))
            self.assertEqual(pred.model_id, "hgb-realizable-v2")
            self.assertIn("artifacts/opt_model/model_hgb_v2.pkl", pred.run_id)

    def test_no_torch_no_checkpoint_import(self):
        import ast
        import inspect

        import goal_adapter.predictions as module

        # CheckpointNotImported：只传谱系字段，禁 import 模型权重/torch
        # （AST import 层扫描，docstring 提及不计）。
        tree = ast.parse(inspect.getsource(module))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("torch", imported)
        self.assertFalse({"pickle", "joblib", "sklearn"} & imported)
        self.assertFalse({"train_realizable", "models"} & imported)

    def test_duplicate_code_date_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pred.parquet"
            _write(path, _frame([
                _row("000001.SZ", "2024-04-02", 0.02, 0.01),
                _row("000001.SZ", "2024-04-02", 0.03, 0.02),
            ]))
            with self.assertRaises(ValueError):
                _adapter(path)


class RealSampleTests(unittest.TestCase):
    PRED = Path("artifacts/baseline/pred_test.parquet")
    SYNTH = Path("backtest/synth_good.parquet")

    def _check_file(self, path):
        names = pq.ParquetFile(str(path)).schema.names
        for col in ["code", "kline_time", "score", "future_ret_5d", "q_true"]:
            self.assertIn(col, names)
        sample = pq.read_table(str(path), columns=["code", "kline_time", "score", "future_ret_5d"])
        frame = sample.to_pandas()
        first_day = frame["kline_time"].iloc[0]
        group = frame[frame["kline_time"] == first_day]
        self.assertGreater(len(group), 100)
        raw_ic = float(group["score"].corr(group["future_ret_5d"], method="spearman"))
        neg_ic = float((-group["score"]).corr(group["future_ret_5d"], method="spearman"))
        # 取负恒为符号翻转（-score 交易用口径的恒等式实证）
        self.assertAlmostEqual(neg_ic, -raw_ic, places=12)
        adapter = _adapter(str(path))
        day = cast(date, pd.Timestamp(first_day).date())
        preds = {p.instrument_id: p.value for p in adapter.predictions_for_date(day)}
        spot = group.head(5)
        for record in spot.itertuples():
            self.assertAlmostEqual(preds[record.code], -float(record.score))

    def test_real_pred_parquet_columns_and_sign(self):
        if not self.PRED.exists():
            self.skipTest(f"真实 pred 缺失：{self.PRED}")
        self._check_file(self.PRED)

    def test_synth_pred_parquet_columns_and_sign(self):
        if not self.SYNTH.exists():
            self.skipTest(f"合成 pred 缺失：{self.SYNTH}")
        self._check_file(self.SYNTH)


if __name__ == "__main__":
    unittest.main()
