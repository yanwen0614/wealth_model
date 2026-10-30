"""训练数据代码级排除名单（黑名单）加载与过滤。

背景与结论（2026-10-30，来源见 `data/excluded_codes.json` 的 sources 段）：
- dev 侧 200 只退市股完全没有 kline 文件（`KlineDayUpdatePipeline` 只更新 active 码）；
- 13 只“暂停上市”股只是区间停牌，有完整正常交易历史，**不得**排除；
- 上述 213 只候选经逐一核对，在两个训练 parquet 中要么 0 行（200 只），
  要么有大量正常交易行（13 只），因此当前名单 `excluded` 为空。

本模块只做代码级过滤：**绝不修改 parquet 原文件**。
名单变更必须改 `data/excluded_codes.json` 并在 commit 说明依据；名单 digest 进入
scaler identity / 缓存 key，故变更会自动使旧缓存与旧 scaler 失效。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from data.identity import canonical_bytes, canonical_hash

DEFAULT_EXCLUDED_CODES_PATH = str(Path(__file__).resolve().parent / "excluded_codes.json")
SCHEMA_VERSION = 1


def resolve_excluded_codes_path(path: str | None = None) -> str:
    """解析名单文件路径：显式 path > 默认（本模块同目录的 excluded_codes.json）。"""
    return os.path.abspath(path) if path else DEFAULT_EXCLUDED_CODES_PATH


def load_excluded_codes(path: str | None = None) -> frozenset[str]:
    """读取黑名单代码集合；文件缺失/结构非法直接报错（不做静默空名单降级）。"""
    resolved = resolve_excluded_codes_path(path)
    with open(resolved, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"黑名单文件结构非法（非对象）: {resolved}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"黑名单 schema_version 不支持: {payload.get('schema_version')!r}, 期望 {SCHEMA_VERSION}"
        )
    entries = payload.get("excluded")
    if not isinstance(entries, list):
        raise TypeError(f"黑名单文件缺少 excluded 列表: {resolved}")
    codes: set[str] = set()
    for item in entries:
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(code, str) or not code:
            raise TypeError(f"黑名单条目缺少合法 code: {item!r}")
        codes.add(code)
    return frozenset(codes)


def excluded_codes_digest(codes: frozenset[str] | set[str]) -> str:
    """名单的 canonical sha256（排序后入 digest，保证与条目顺序无关）。"""
    return canonical_hash({"excluded_codes": sorted(codes), "schema_version": SCHEMA_VERSION})


def excluded_codes_identity(path: str | None = None) -> dict:
    """名单 identity：路径 + 代码集 + digest，供 scaler identity / cache key 绑定。"""
    resolved = resolve_excluded_codes_path(path)
    codes = load_excluded_codes(resolved)
    return {
        "excluded_codes_path": resolved,
        "excluded_codes_count": len(codes),
        "excluded_codes_digest": excluded_codes_digest(codes),
    }


def filter_excluded_codes(df: pd.DataFrame, codes: frozenset[str] | set[str],
                          label: str = "ParquetDataset") -> pd.DataFrame:
    """过滤黑名单代码的全部行；空名单时原样返回并仍打印可观测日志。"""
    before = len(df)
    if codes:
        df = df[~df["code"].isin(codes)]
    print(
        f"[{label}] 排除黑名单代码: {len(codes)} 只, {before:,} -> {len(df):,} 行 "
        f"(drop {before - len(df):,})"
    )
    return df


__all__ = [
    "DEFAULT_EXCLUDED_CODES_PATH",
    "canonical_bytes",
    "excluded_codes_digest",
    "excluded_codes_identity",
    "filter_excluded_codes",
    "load_excluded_codes",
    "resolve_excluded_codes_path",
]
