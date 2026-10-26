"""独立生成因果模型信号；信号资格不依赖未来标签。"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from config.defaults import DEFAULT_BINS, DEFAULT_CENTERS
from data.scaler import RelativeScaler
from data.schema import APPROVED_RAW_FEATURES, FEATURE_GROUPS
from models.cnn_transformer.config import ModelConfig
from models.cnn_transformer.model import CNNTransformer
from training.checkpoint import load_model_state
from training.preprocessing import load_run_config

F4_RAW_FEATURES = ("open", "high", "low", "close")
F29_FINANCIAL_FEATURES = frozenset({"gross_margin", "net_margin", "roe", "roa", "debt_to_equity"})
F29_RAW_FEATURES = tuple(FEATURE_GROUPS["P"]) + tuple(
    column for column in FEATURE_GROUPS["R"] if column not in F29_FINANCIAL_FEATURES
)


def _relative_scaler(contract: SignalContract) -> RelativeScaler:
    use_shared_mask = tuple(contract.feature_cols) == tuple(APPROVED_RAW_FEATURES)
    return RelativeScaler(contract.feature_cols, add_mask=use_shared_mask)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class SignalContract:
    checkpoint: str
    run_config: dict
    feature_cols: list[str]
    feature_cols_out: list[str]
    seq_len: int
    horizon: int
    label_mode: str
    model_config: dict


def _checkpoint_contract(path: str) -> SignalContract:
    if not Path(path).is_file():
        raise FileNotFoundError(f"checkpoint 路径不存在: {path}")
    cfg = load_run_config(path, strict=True)
    pre = cfg.get("preprocessing") or {}
    cols = pre.get("feature_cols")
    out = pre.get("feature_cols_out")
    model_cfg = cfg.get("CNNTransformerConfig")
    if not isinstance(cols, list) or not isinstance(out, list) or not isinstance(model_cfg, dict):
        raise TypeError("checkpoint config 缺少 feature_cols/feature_cols_out/CNNTransformerConfig")
    seq_len = int(cfg.get("SEQ_LEN", pre.get("seq_len", 0)))
    horizon = int(cfg.get("HORIZON", 0))
    mode = pre.get("mode", cfg.get("NORMALIZE"))
    label_mode = cfg.get("LABEL_MODE")
    if seq_len != 60 or horizon != 10 or mode != "relative" or cfg.get("NORMALIZE") != "relative":
        raise ValueError("仅接受 seq_len=60、HORIZON=10、relative 的 checkpoint")
    split = [cfg.get(key) for key in ("TRAIN_START", "TRAIN_END", "VAL_START", "VAL_END")]
    if any(value is None for value in split):
        raise ValueError("checkpoint config 缺少 TRAIN/VAL 日期边界")
    train_start, train_end, val_start, val_end = map(pd.Timestamp, split)
    if not (train_start <= train_end < val_start <= val_end):
        raise ValueError("checkpoint TRAIN/VAL 日期边界不满足严格时序")
    if label_mode != "excess":
        raise ValueError("本工程只接受 LABEL_MODE=excess 的 checkpoint")
    if tuple(cols) == tuple(APPROVED_RAW_FEATURES):
        expected_features = 53
    elif tuple(cols) == F29_RAW_FEATURES:
        expected_features = 29
    elif tuple(cols) == F4_RAW_FEATURES:
        expected_features = 4
    else:
        raise ValueError("checkpoint raw feature schema 不受支持；仅接受有序 F53、F29 或 F4")
    scaler = RelativeScaler(cols, add_mask=expected_features == 53)
    if scaler.feature_cols_out != out or len(out) != expected_features:
        raise ValueError("checkpoint feature_cols_out 与所选 raw feature schema 不匹配")
    if (int(model_cfg.get("featurenum", -1)) != expected_features
            or int(pre.get("featurenum", -1)) != expected_features):
        raise ValueError(f"checkpoint featurenum 必须为 {expected_features}")
    if (int(model_cfg.get("num_classes", -1)) != 52 or int(model_cfg.get("seq_len", -1)) != 60
            or model_cfg.get("gate_head") is not False
            or int(cfg.get("num_classes", -1)) != 52):
        raise ValueError("checkpoint num_classes 必须为 52")
    if int(pre.get("seq_len", -1)) != seq_len or int(pre.get("num_classes", -1)) != 52:
        raise ValueError("preprocessing 序列长度/类别数与模型配置不一致")
    bins = np.asarray(cfg.get("BINS", []), dtype=np.float64)
    if bins.shape != (51,) or not np.array_equal(bins, np.asarray(DEFAULT_BINS)):
        raise ValueError("checkpoint BINS 与训练 52 类 schema 不一致")
    centers = np.asarray(cfg.get("CENTERS", []), dtype=np.float64)
    if not np.array_equal(centers, np.asarray(DEFAULT_CENTERS)):
        raise ValueError("checkpoint CENTERS 与 BINS 派生中心不一致")
    if cfg.get("CS_RANK") is not False or cfg.get("MKT_FACTORS") is not False:
        raise ValueError("signal-only 契约不接受 cs_rank/mkt 因子旁路列")
    if cfg.get("PURE_REG") is not False or cfg.get("GATE_HEAD") is not False:
        raise ValueError("首版信号生成要求分类模型且关闭 PURE_REG/GATE_HEAD")
    return SignalContract(path, cfg, cols, out, seq_len, horizon, label_mode, model_cfg)


def _read_causal_frame(path: str, contract: SignalContract, decision_start: pd.Timestamp,
                       buffer_end: pd.Timestamp) -> pd.DataFrame:
    parquet = pq.ParquetFile(path)
    names = set(parquet.schema.names)
    required = {"code", "kline_time", "open", "close", "is_trading", *contract.feature_cols}
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"parquet 缺少 checkpoint 特征/标识列: {missing}")
    columns = sorted(required)
    history: dict[str, pd.DataFrame] = {}
    period: list[pd.DataFrame] = []
    max_batch_rows = 0
    for batch in parquet.iter_batches(batch_size=131072, columns=columns):
        chunk = batch.to_pandas()
        max_batch_rows = max(max_batch_rows, len(chunk))
        chunk["kline_time"] = pd.to_datetime(chunk["kline_time"], errors="coerce")
        chunk = chunk.loc[chunk["kline_time"].notna()].copy()
        chunk["code"] = chunk["code"].astype(str)
        chunk["_is_trading"] = chunk["is_trading"].eq(True)
        before = chunk.loc[(chunk["kline_time"] < decision_start) & chunk["_is_trading"]]
        for code, rows in before.groupby("code", sort=False):
            previous = history.get(code)
            merged = rows if previous is None else pd.concat((previous, rows), ignore_index=True)
            history[code] = merged.sort_values("kline_time", kind="stable").tail(contract.seq_len - 1)
        active = chunk.loc[chunk["kline_time"].between(decision_start, buffer_end)]
        if not active.empty:
            period.append(active)
    history_rows = list(history.values())
    parts = history_rows + period
    frame = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)
    context_count = sum(map(len, history_rows))
    period_count = sum(map(len, period))
    del parts, history_rows, period
    frame = frame.sort_values(["code", "kline_time"], kind="stable").reset_index(drop=True)
    frame.attrs["read_stats"] = {
        "row_groups_scanned": parquet.num_row_groups, "max_batch_rows": max_batch_rows,
        "context_rows_retained": context_count, "period_rows_retained": period_count,
        "context_limit_per_code": contract.seq_len - 1,
        "read_mode": "row_group_streaming; per-code last valid rows before decision_start",
    }
    return frame


def causal_window(frame: pd.DataFrame, contract: SignalContract, code: str,
                  decision_date: pd.Timestamp) -> tuple[np.ndarray | None, str]:
    rows = frame.loc[(frame["code"] == code) & (frame["kline_time"] <= decision_date)]
    day = rows.loc[rows["kline_time"] == decision_date]
    if day.empty:
        return None, "no_row_on_decision_date"
    if not bool(day.iloc[-1]["_is_trading"]):
        return None, "not_trading"
    valid = rows.loc[rows["_is_trading"]]
    if valid.empty or valid.iloc[-1]["kline_time"] != decision_date:
        return None, "not_trading"
    if len(valid) < contract.seq_len:
        return None, "insufficient_history"
    raw = valid[contract.feature_cols].to_numpy(dtype=np.float64)
    close = valid["close"].to_numpy(dtype=np.float64)
    features = _relative_scaler(contract).transform_code(
        code, raw, contract.feature_cols, close
    )
    if features.shape[1] != len(contract.feature_cols_out):
        return None, "feature_schema_mismatch"
    return np.ascontiguousarray(features[-contract.seq_len:].T, dtype=np.float32), "ready"


def _prepare_code_groups(frame: pd.DataFrame, contract: SignalContract) -> dict[str, tuple[dict, dict]]:
    prepared: dict[str, tuple[dict, dict]] = {}
    scaler = _relative_scaler(contract)
    for code, group in frame.groupby("code", sort=False):
        group = group.sort_values("kline_time", kind="stable")
        status_by_date = dict(zip(group["kline_time"], group["_is_trading"].astype(bool)))
        valid = group.loc[group["_is_trading"]]
        if valid.empty:
            prepared[str(code)] = (status_by_date, {})
            continue
        raw = valid[contract.feature_cols].to_numpy(dtype=np.float64)
        close = valid["close"].to_numpy(dtype=np.float64)
        features = scaler.transform_code(str(code), raw, contract.feature_cols, close)
        positions = {date: i for i, date in enumerate(valid["kline_time"])}
        prepared[str(code)] = (status_by_date, {"positions": positions, "features": features})
    return prepared


def _validate_decision_start(contract: SignalContract, decision_start: pd.Timestamp) -> None:
    val_end = pd.Timestamp(contract.run_config["VAL_END"])
    if val_end >= decision_start:
        raise ValueError("decision_start 必须晚于 checkpoint 的 VAL_END")


def _resolve_buffer_dates(calendar: pd.DatetimeIndex, end_pos: int,
                          buffer_sessions: int) -> pd.DatetimeIndex:
    if buffer_sessions < 1:
        raise ValueError("清算 buffer 至少需要 1 个交易日")
    dates = calendar[end_pos + 1:end_pos + 1 + buffer_sessions]
    if len(dates) != buffer_sessions:
        raise ValueError("显式真实交易日历未包含完整清算 buffer")
    return dates


@torch.no_grad()
def generate_signals(checkpoint: str, parquet: str, start: str, end: str,
                     calendar: pd.DatetimeIndex, batch_size: int = 256,
                     buffer_sessions: int = 3) -> pd.DataFrame:
    """按 code-date 生成因果信号；true_ret 不加载并保留为 NaN。"""
    contract = _checkpoint_contract(checkpoint)
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).tz_localize(None).normalize().unique().sort_values()
    lower, upper = pd.Timestamp(start), pd.Timestamp(end)
    if lower > upper or lower not in calendar or upper not in calendar:
        raise ValueError("决策边界必须位于显式交易日历中且区间有效")
    _validate_decision_start(contract, lower)
    start_pos, end_pos = calendar.get_loc(lower), calendar.get_loc(upper)
    decision_dates = calendar[start_pos:end_pos + 1]
    buffer_dates = _resolve_buffer_dates(calendar, end_pos, buffer_sessions)
    frame = _read_causal_frame(parquet, contract, lower, buffer_dates[-1])
    dates = list(decision_dates)
    prepared = _prepare_code_groups(frame, contract)
    first_seen = {code: min(status) for code, (status, _) in prepared.items() if status}
    codes = sorted(first_seen)
    mc = contract.model_config
    model = CNNTransformer(ModelConfig(
        featurenum=int(mc["featurenum"]), seq_len=contract.seq_len, num_classes=52,
        cnn_out_channels=int(mc.get("cnn_out_channels", 128)),
        cnn_kernel_sizes=list(mc.get("cnn_kernel_sizes", [1, 3, 5, 7, 10])),
        d_model=int(mc.get("d_model", 256)), nhead=int(mc.get("nhead", 8)),
        num_encoder_layers=int(mc.get("num_encoder_layers", 4)),
        dropout_rate=float(mc.get("dropout_rate", 0.3)), gate_head=bool(mc.get("gate_head", False)),
    ))
    load_model_state(checkpoint, model, map_location="cpu", strict=True)
    model.eval()
    records: list[dict] = []
    pending: list[tuple[str, pd.Timestamp, np.ndarray, bool]] = []

    def flush() -> None:
        if not pending:
            return
        x = torch.from_numpy(np.stack([item[2] for item in pending]))
        output = model(x)
        if not isinstance(output, tuple) or len(output) != 2:
            raise TypeError("CNNTransformer checkpoint 必须返回 logits 与回归头输出")
        logits = output[0]
        probs = torch.softmax(logits, dim=1).cpu().numpy()
        exp = probs @ np.asarray(DEFAULT_CENTERS, dtype=np.float64)
        for item, value in zip(pending, exp):
            records.append(_signal_record(item[0], item[1], float(value), "ready", item[3]))
        pending.clear()

    for date_value in dates:
        date = pd.Timestamp(date_value)
        in_decision = date < upper  # 期末收盘信号保留，但次日进入 buffer 时禁止新开仓
        for code in codes:
            if first_seen[code] > date:
                continue
            status_by_date, payload = prepared[code]
            if date not in status_by_date:
                reason, window = "no_row_on_decision_date", None
            elif not status_by_date[date]:
                reason, window = "not_trading", None
            else:
                pos = payload["positions"][date]
                if pos + 1 < contract.seq_len:
                    reason, window = "insufficient_history", None
                else:
                    window = np.ascontiguousarray(
                        payload["features"][pos - contract.seq_len + 1:pos + 1].T,
                        dtype=np.float32,
                    )
                    reason = "ready"
            if window is None:
                records.append(_signal_record(code, date, np.nan, reason, in_decision))
            else:
                pending.append((code, date, window, in_decision))
                if len(pending) >= batch_size:
                    flush()
    flush()
    result = pd.DataFrame(records)
    parquet_file = pq.ParquetFile(parquet)
    read_stats = frame.attrs["read_stats"]
    retained_rows = read_stats["context_rows_retained"] + read_stats["period_rows_retained"]
    estimated_payload = retained_rows * (len(contract.feature_cols) * 8 + len(contract.feature_cols_out) * 4) * 2
    result.attrs["metadata"] = {
        "checkpoint": str(Path(checkpoint).resolve()), "parquet": str(Path(parquet).resolve()),
        "checkpoint_sha256": _sha256(checkpoint),
        "config_sha256": _sha256(str(Path(checkpoint).with_name("config.json"))),
        "generator_sha256": _sha256(__file__),
        "parquet_size_bytes": Path(parquet).stat().st_size,
        "parquet_row_count": parquet_file.metadata.num_rows,
        "parquet_schema_sha256": hashlib.sha256(str(parquet_file.schema_arrow).encode()).hexdigest(),
        "row_group_read_stats": read_stats,
        "estimated_peak_numeric_payload_mib": round(estimated_payload / (1024 ** 2), 2),
        "label_mode": contract.label_mode, "normalize": "relative", "seq_len": 60,
        "horizon": 10, "featurenum": len(contract.feature_cols_out),
        "feature_cols": contract.feature_cols,
        "feature_cols_out": contract.feature_cols_out, "bins": DEFAULT_BINS,
        "train_start": contract.run_config["TRAIN_START"],
        "train_end": contract.run_config["TRAIN_END"],
        "val_start": contract.run_config["VAL_START"],
        "val_end": contract.run_config["VAL_END"],
        "exp_ret_semantics": "excess_return_expectation_from_class_centers",
        "decision_start": start, "decision_end": end,
        "decision_calendar": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in decision_dates],
        "liquidation_buffer_calendar": [pd.Timestamp(d).strftime("%Y-%m-%d") for d in buffer_dates],
        "terminal_execution_policy": {
            "buy": "allow only when execution_date <= decision_end; reject BUY in post-E buffer",
            "sell": "allow during post-E liquidation buffer",
            "writer_policy": "retain every valid signal through decision_end, including E close",
        },
        "true_ret_semantics": "NaN; signal qualification is future-label independent",
    }
    return result


def _signal_record(code: str, date: pd.Timestamp, exp_ret: float,
                   status: str, buy_eligible: bool) -> dict:
    return {
        "code": code, "date": date, "exp_ret": exp_ret, "true_ret": np.nan,
        "status": status, "label_availability": "not_loaded",
        "buy_eligible": bool(buy_eligible and status == "ready"),
    }


def prediction_cache_arrays(signals: pd.DataFrame) -> dict[str, np.ndarray]:
    """保留决策期所有信号；执行资格由 terminal wrapper 按成交日裁决。"""
    if "buy_eligible" not in signals:
        raise ValueError("信号表缺少 buy_eligible 元数据")
    return {
        "exp_ret": signals["exp_ret"].to_numpy(dtype=np.float64),
        "true_ret": np.full(len(signals), np.nan, dtype=np.float64),
        "dates": pd.to_datetime(signals["date"]).to_numpy(dtype="datetime64[ns]"),
        "codes": signals["code"].to_numpy(dtype=str),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, help="best_model.pth；无 latest 回退")
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--calendar", required=True, help="000300.SH 真实交易日历 CSV/parquet")
    parser.add_argument("--decision-start", required=True)
    parser.add_argument("--decision-end", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        raise ValueError("batch-size 必须为正数")
    if args.calendar.lower().endswith(".parquet"):
        calendar_frame = pd.read_parquet(args.calendar)
    else:
        calendar_frame = pd.read_csv(args.calendar)
    date_col = "date" if "date" in calendar_frame else "kline_time"
    if date_col not in calendar_frame:
        raise ValueError("交易日历必须包含 date 或 kline_time 列")
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar_frame[date_col], errors="raise"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    signals = generate_signals(args.checkpoint, args.parquet, args.decision_start,
                               args.decision_end, calendar, args.batch_size)
    signals.attrs["metadata"]["calendar_path"] = str(Path(args.calendar).resolve())
    signals.to_parquet(out_dir / "signals.parquet", index=False)
    with (out_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(signals.attrs["metadata"], handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
