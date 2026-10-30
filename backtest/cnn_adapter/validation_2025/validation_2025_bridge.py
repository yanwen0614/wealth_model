"""仅供2025历史回放使用的NPZ身份校验与冻结Parquet桥接。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

REQUIRED_NPZ_KEYS = frozenset({"dates", "codes", "exp_ret", "true_ret"})
MODEL_HORIZON = 10
EXP_RET_SEMANTICS = (
    "exp_ret=(probs*centers52).sum(-1),centers52=bins_to_centers(BINS); "
    "H10训练标签期望收益排序，交易持有政策独立"
)
_PARQUET_SCHEMA = pa.schema([
    ("date", pa.date32()), ("code", pa.string()), ("exp_ret", pa.float64()),
    ("true_ret", pa.float64()), ("status", pa.string()), ("buy_eligible", pa.bool_()),
    ("execution_status", pa.string()), ("buy_rejection_reasons", pa.list_(pa.string())),
    *[(name, pa.string()) for name in ("state_source_sha256", "source_npz_sha256",
        "source_npz_path", "checkpoint_sha256", "config_sha256", "source_report_sha256",
        "checkpoint_path", "config_path")],
    ("model_horizon", pa.int64()), ("signal_produced_at", pa.string()),
    ("signal_semantics", pa.string()), ("identity_status", pa.string()),
])


class Validation2025Error(ValueError):
    """2025桥接输入、身份或窗口不满足冻结协议。"""


@dataclass(frozen=True)
class NpzSignal:
    dates: tuple[date, ...]
    codes: tuple[str, ...]
    exp_ret: tuple[float, ...]
    true_ret: tuple[float, ...]
    source_sha256: str


@dataclass(frozen=True)
class FrozenParquetResult:
    path: Path
    source_sha256: str
    parquet_sha256: str
    row_count: int
    source_report_sha256: str


@dataclass(frozen=True)
class EligibilityDecision:
    buy_eligible: bool
    execution_status: str
    reasons: tuple[str, ...]


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def atomic_output_directory(output_dir: str | Path):
    """在目标同级临时目录准备产物，全部成功后再发布为目标目录。"""
    output = Path(output_dir)
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.tmp-", dir=parent) as temp:
        staged = Path(temp)
        yield staged
        staged.rename(output)


def _checked_sha(path: str | Path, expected: str, label: str) -> str:
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in "0123456789abcdef" for c in expected.lower())
            or set(expected.lower()) == {"0"}):
        raise Validation2025Error(f"{label}需要非全零SHA-256")
    actual = file_sha256(path)
    if actual != expected.lower():
        raise Validation2025Error(f"{label} SHA-256不匹配: expected={expected}, actual={actual}")
    return actual


def load_npz_signal(path: str | Path, *, expected_sha256: str) -> NpzSignal:
    """先校验原始文件字节SHA，再严格读取四数组；不保存或改写NPZ。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = _checked_sha(source, expected_sha256, "NPZ")
    try:
        with np.load(source, allow_pickle=False) as archive:
            if set(archive.files) != REQUIRED_NPZ_KEYS:
                raise Validation2025Error(f"NPZ键必须恰为{sorted(REQUIRED_NPZ_KEYS)}")
            arrays = {key: np.asarray(archive[key]) for key in REQUIRED_NPZ_KEYS}
    except Validation2025Error:
        raise
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        raise Validation2025Error(f"NPZ无法安全解码: {source}") from error
    if any(array.ndim != 1 for array in arrays.values()):
        raise Validation2025Error("NPZ四个数组必须是一维")
    lengths = {len(array) for array in arrays.values()}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
        raise Validation2025Error("NPZ四数组必须非空且长度完全一致")
    if arrays["dates"].dtype.kind != "M" or np.isnat(arrays["dates"]).any():
        raise Validation2025Error("dates必须是numpy datetime64数组")
    if arrays["codes"].dtype.kind not in "US":
        raise Validation2025Error("codes必须是定长Unicode或UTF-8字节数组")
    if any(arrays[key].dtype.kind not in "fiu" for key in ("exp_ret", "true_ret")):
        raise Validation2025Error("exp_ret/true_ret必须为数值数组")
    if not np.isfinite(arrays["exp_ret"]).all() or not np.isfinite(arrays["true_ret"]).all():
        raise Validation2025Error("exp_ret/true_ret含NaN或无穷值")
    days = tuple(value.astype("datetime64[D]").astype(date)
                 for value in arrays["dates"])
    if any(value.astype("datetime64[D]") != value for value in arrays["dates"]):
        raise Validation2025Error("dates必须位于交易日零点")
    codes = tuple(value.decode("utf-8") if isinstance(value, bytes) else str(value)
                  for value in arrays["codes"])
    if any(not code or code.strip() != code for code in codes):
        raise Validation2025Error("codes必须为无空白的非空字符串")
    keys = tuple(zip(days, codes, strict=True))
    if len(set(keys)) != len(keys):
        raise Validation2025Error("NPZ存在重复(date, code)键")
    if any(day.year != 2025 for day in days):
        raise Validation2025Error("NPZ信号日期必须属于2025")
    return NpzSignal(days, codes, tuple(map(float, arrays["exp_ret"])),
                     tuple(map(float, arrays["true_ret"])), digest)


def assert_ab_equivalent(left: NpzSignal, right: NpzSignal) -> None:
    """要求A/B行序、日期、代码和标签逐元素相同，分数保持各自独立。"""
    if left.dates != right.dates or left.codes != right.codes or left.true_ret != right.true_ret:
        raise Validation2025Error("A/B日期、代码、true_ret未逐元素完全对齐")


def derive_buy_eligibility(signal: NpzSignal, execution_calendar, states):
    """只依据收盘决策时已知状态拒绝unknown，避免窥视次日开盘状态。"""
    calendar = tuple(execution_calendar)
    if calendar != tuple(sorted(set(calendar))) or not calendar:
        raise Validation2025Error("execution_calendar必须递增且无重复")
    index = {day: pos for pos, day in enumerate(calendar)}
    decisions = {}
    required_true = ("st_known", "reference_known", "limit_known", "listing_known",
                     "quantity_rule_known", "corporate_action_known")
    for day, code in zip(signal.dates, signal.codes, strict=True):
        position = index.get(day)
        if position is None or position == len(calendar) - 1:
            raise Validation2025Error(f"信号日无下一执行日: {day}")
        state = states.get((code, day))
        if not isinstance(state, Mapping):
            raise Validation2025Error(f"缺少候选信号日收盘状态: {code} {day}")
        reasons = []
        market_state = state.get("market_state")
        if market_state != "trading":
            reasons.append(f"market_state={market_state!r}")
        for field in required_true:
            if state.get(field) is not True:
                reasons.append(f"{field}_unknown")
        for field in ("limit_up", "limit_down"):
            if type(state.get(field)) is not bool:
                reasons.append(f"{field}_unknown")
            elif state[field]:
                reasons.append(field)
        if type(state.get("st_flag")) is not bool:
            reasons.append("st_flag_unknown")
        for field in ("absolute_limit_up_price", "absolute_limit_down_price"):
            value = state.get(field)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or value <= 0):
                reasons.append(f"{field}_unknown")
        status = str(market_state) if market_state in ("trading", "suspended") else "unknown"
        decisions[day, code] = EligibilityDecision(not reasons, status, tuple(reasons))
    return decisions


def _horizons(value):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in {"horizon", "label_horizon", "prediction_horizon"}:
                yield item
            yield from _horizons(item)
    elif isinstance(value, list):
        for item in value:
            yield from _horizons(item)


def _validate_config(path: str | Path, expected_sha256: str) -> tuple[str, str]:
    config_path = Path(path)
    digest = _checked_sha(config_path, expected_sha256, "模型config")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Validation2025Error("模型config必须是可读JSON以核HORIZON=10") from error
    values = list(_horizons(config))
    if values != [MODEL_HORIZON]:
        raise Validation2025Error(f"模型config必须唯一声明HORIZON=10，实际为{values}")
    return str(config_path.resolve()), digest


def _validate_source_report(path, expected_sha, signal_sha, checkpoint_sha, config_sha, produced_at):
    expected = {"npz_sha256": signal_sha, "checkpoint_sha256": checkpoint_sha,
                "config_sha256": config_sha, "produced_at": produced_at,
                "model_horizon": MODEL_HORIZON}
    if path is None:
        payload = {"source": "local_artifact_identity", "external_attestation": False,
                   **expected}
        return hashlib.sha256(json.dumps(payload, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
    report_sha = _checked_sha(path, expected_sha, "独立来源报告")
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Validation2025Error("独立来源报告必须是可读JSON") from error
    if not isinstance(report, Mapping):
        raise Validation2025Error("独立来源报告顶层必须为对象")
    if any(report.get(key) != value for key, value in expected.items()):
        raise Validation2025Error("独立来源报告未绑定NPZ/checkpoint/config/产生时间/H10")
    return report_sha


def convert_npz_to_frozen_parquet(
    npz_path: str | Path, *, expected_npz_sha256: str,
    checkpoint_path: str | Path, expected_checkpoint_sha256: str,
    config_path: str | Path, expected_config_sha256: str,
    source_report_path: str | Path | None = None,
    expected_report_sha256: str | None = None,
    produced_at: str, eligibility: Mapping[tuple[date, str], EligibilityDecision],
    state_source_path: str | Path, expected_state_source_sha256: str,
    output_dir: str | Path,
) -> FrozenParquetResult:
    """将NPZ逐行桥接给runner；缺少明确资格或任何身份核验则停止。"""
    signal = load_npz_signal(npz_path, expected_sha256=expected_npz_sha256)
    checkpoint_sha = _checked_sha(checkpoint_path, expected_checkpoint_sha256, "checkpoint")
    config_resolved, config_sha = _validate_config(config_path, expected_config_sha256)
    try:
        instant = datetime.fromisoformat(produced_at)
    except ValueError as error:
        raise Validation2025Error("produced_at必须为带时区ISO时间") from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise Validation2025Error("produced_at必须包含时区")
    report_sha = _validate_source_report(source_report_path, expected_report_sha256,
        signal.source_sha256, checkpoint_sha, config_sha, produced_at)
    state_sha = _checked_sha(state_source_path, expected_state_source_sha256, "状态来源")
    expected_keys = set(zip(signal.dates, signal.codes, strict=True))
    if (set(eligibility) != expected_keys
            or any(not isinstance(v, EligibilityDecision) for v in eligibility.values())):
        raise Validation2025Error("eligibility必须为每个NPZ(date,code)提供状态派生决策")
    if any(decision.buy_eligible and decision.reasons for decision in eligibility.values()):
        raise Validation2025Error("存在带拒绝原因却允许买入的状态冲突")
    if any(decision.execution_status not in {"trading", "suspended", "unknown"}
           or (decision.execution_status == "unknown" and decision.buy_eligible)
           for decision in eligibility.values()):
        raise Validation2025Error("执行状态未知时必须拒绝买入")
    out = Path(output_dir)
    with atomic_output_directory(out) as staged:
        parquet_path = staged / "signals.parquet"
        with parquet_path.open("xb") as stream:
            writer = pq.ParquetWriter(stream, _PARQUET_SCHEMA, compression="zstd")
            for offset in range(0, len(signal.dates), 25_000):
                stop = min(offset + 25_000, len(signal.dates))
                rows = []
                for index in range(offset, stop):
                    day, code = signal.dates[index], signal.codes[index]
                    decision = eligibility[day, code]
                    rows.append({"date": day, "code": code,
                         "exp_ret": signal.exp_ret[index], "true_ret": signal.true_ret[index],
                         "status": "ready",
                         "buy_eligible": decision.buy_eligible,
                         "execution_status": decision.execution_status,
                         "buy_rejection_reasons": list(decision.reasons),
                         "state_source_sha256": state_sha,
                         "source_npz_sha256": signal.source_sha256,
                         "source_npz_path": str(Path(npz_path).resolve()),
                         "checkpoint_sha256": checkpoint_sha, "config_sha256": config_sha,
                         "source_report_sha256": report_sha,
                         "checkpoint_path": str(Path(checkpoint_path).resolve()),
                         "config_path": config_resolved, "model_horizon": MODEL_HORIZON,
                         "signal_produced_at": produced_at,
                         "signal_semantics": EXP_RET_SEMANTICS,
                         "identity_status": "IDENTITY_LOCAL"})
                writer.write_table(pa.Table.from_pylist(rows, schema=_PARQUET_SCHEMA))
            writer.close()
        parquet_sha = file_sha256(parquet_path)
    published_path = out / "signals.parquet"
    return FrozenParquetResult(published_path, signal.source_sha256,
                               parquet_sha, len(signal.dates), report_sha)
