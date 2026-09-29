"""training preprocessing 唯一事实源（T08）。

收敛三入口 `configure_preprocessing` 镜像（train / train_retail / multi_seed）
与双 eval 脚本 scaler 解析（eval_bins_mapping / run_eval_pipeline）：
rolling 产物路径隔离、relative 无 state、per_code 复用、异 scope 拒绝。
零行为变更：语义逐字沿用 train.py:52 / eval_bins_mapping.resolve_scaler_path。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

ROLLING_SCOPES = ("e0", "e1", "e2", "e3", "e4", "e5")
DEFAULT_ROLLING_SCOPE = "e5"
NORMALIZE_MODES = frozenset({"relative", "per_code", "rolling"})
EVAL_MODES = frozenset({"relative", "per_code", "rolling"})
ROLLING_DEFAULT_SCALER_PATH = "logs/rolling_e5/scaler_rolling_e5.pkl"
PER_CODE_DEFAULT_SCALER_PATH = "logs/scaler_per_code.pkl"


def configure_preprocessing(
    config: dict, normalize: str, rolling_scope: str = "e5", *, retail: bool = False
) -> None:
    """按 mode/scope 隔离 SCALER_PATH/LOG_DIR（relative 无持久 state）。

    retail=True 时 LOG_DIR 走 `./logs/retail_*` 命名空间（train_retail 语义），
    否则走主链路 `./logs[/rolling_{scope}|/relative]`（train/multi_seed 语义）。
    非 rolling 不碰 ROLLING_SCOPE；未知 mode/scope 直接抛错，禁静默默认。
    """
    if normalize not in NORMALIZE_MODES:
        raise ValueError(f"未知 normalize: {normalize}")
    config["NORMALIZE"] = normalize
    ns = "retail_" if retail else ""
    if normalize == "per_code":
        config["SCALER_PATH"] = PER_CODE_DEFAULT_SCALER_PATH
        config["LOG_DIR"] = f"./logs/{ns}per_code" if ns else "./logs"
    elif normalize == "rolling":
        if rolling_scope not in ROLLING_SCOPES:
            raise ValueError(f"未知 rolling_scope: {rolling_scope!r}，仅支持 {'/'.join(ROLLING_SCOPES)}")
        config["ROLLING_SCOPE"] = rolling_scope
        config["SCALER_PATH"] = f"logs/rolling_{rolling_scope}/scaler_rolling_{rolling_scope}.pkl"
        config["LOG_DIR"] = f"./logs/{ns}rolling_{rolling_scope}"
    else:  # relative：无统计 state，列规则确定性重建
        config["SCALER_PATH"] = None
        config["LOG_DIR"] = f"./logs/{ns}relative"


def default_scaler_path(mode: str) -> str | None:
    """各 mode scaler 回退路径：relative 无持久 state，rolling 缺省 e5。"""
    if mode == "relative":
        return None
    return ROLLING_DEFAULT_SCALER_PATH if mode == "rolling" else PER_CODE_DEFAULT_SCALER_PATH


def resolve_eval_scaler_path(
    run_cfg: dict, mode: str | None = None, cli_override: str | None = None
) -> str | None:
    """scaler 路径优先级：CLI > preprocessing state/scaler/SCALER_PATH > 顶层 > 默认。

    mode 缺省时从 checkpoint preprocessing.mode 派生（缺键回退 per_code，
    与 eval 历史语义一致）；relative 恒返 None（无持久 state）。
    """
    if cli_override:
        return cli_override
    metadata = run_cfg.get("preprocessing") or {}
    resolved_mode = mode if mode is not None else metadata.get("mode", "per_code")
    if resolved_mode == "relative":
        return None
    return (
        metadata.get("state_path") or metadata.get("scaler_path") or metadata.get("SCALER_PATH")
        or run_cfg.get("SCALER_PATH")
        or default_scaler_path(resolved_mode)
    )


def resolve_eval_mode_scope(
    run_cfg: dict, cli_scope: str | None = None
) -> tuple[str, str | None]:
    """评估 mode/scope：优先 checkpoint preprocessing，CLI 仅做一致性校验。"""
    metadata = run_cfg.get("preprocessing") or {}
    mode = metadata.get("mode", "per_code")
    if mode not in EVAL_MODES:
        raise ValueError(f"checkpoint preprocessing mode 不支持: {mode}")
    scope = metadata.get("scope")
    if cli_scope is not None:
        if cli_scope not in ROLLING_SCOPES:
            raise ValueError(f"rolling scope 非法: {cli_scope!r}，仅支持 {'/'.join(ROLLING_SCOPES)}")
        if mode == "rolling" and scope is not None and cli_scope != scope:
            raise ValueError(f"rolling scope 不匹配：checkpoint={scope!r} vs 请求={cli_scope!r}")
        if mode == "rolling":
            scope = cli_scope
    if mode == "rolling" and scope is None:
        scope = DEFAULT_ROLLING_SCOPE
    return mode, scope


def resolve_eval_featurenum(run_cfg: dict, cli_featurenum: int | None = None) -> int:
    """featurenum 实测派生：CLI 显式 > metadata.featurenum > len(feature_cols_out)。"""
    metadata = run_cfg.get("preprocessing") or {}
    metadata_featurenum = metadata.get("featurenum")
    if cli_featurenum is not None:
        if metadata_featurenum is not None and int(metadata_featurenum) != int(cli_featurenum):
            raise ValueError(
                f"--featurenum 与 checkpoint metadata 不符: cli={cli_featurenum} metadata={metadata_featurenum}"
            )
        return int(cli_featurenum)
    if metadata_featurenum is not None:
        return int(metadata_featurenum)
    feature_cols_out = metadata.get("feature_cols_out")
    if feature_cols_out:
        return len(feature_cols_out)
    raise ValueError(
        "checkpoint 缺少 preprocessing.featurenum/feature_cols_out，无法派生模型 featurenum；"
        "请提供 metadata 或用 --featurenum 显式指定"
    )


@dataclass(frozen=True)
class EvalPreprocessing:
    """评估预处理契约（canonical 定义；eval 双脚本仅 re-export 兼容）。"""

    mode: str
    scaler_stats: object | None
    feature_cols: list[str] | None
    schema_identity: str | None
    run_config: dict
    scaler_path: str | None
    feature_cols_out: list[str] | None = None


def load_run_config(ckpt_path: str, *, strict: bool = False) -> dict:
    """读 checkpoint 同目录 config.json；缺失时宽松返 {}，strict 抛错。"""
    cfg_path = os.path.join(os.path.dirname(ckpt_path), "config.json")
    if not os.path.exists(cfg_path):
        if strict:
            raise FileNotFoundError(f"checkpoint 同目录缺少 config.json: {cfg_path}")
        return {}
    with open(cfg_path, encoding="utf-8") as handle:
        return json.load(handle)
