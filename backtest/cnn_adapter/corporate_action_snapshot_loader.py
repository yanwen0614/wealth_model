"""从冻结 SQLite 导出保留来源证据；不推断官方实施、税务或舍入规则。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .corporate_actions import CorporateActionEvent, CorporateActionProvider


@dataclass(frozen=True)
class ActionDescriptor:
    """保留无除权日、无阶段以及配股公告，不伪造规范事件。"""

    event_id: str
    instrument_id: str
    source_table: str
    file_sha256: str
    raw_row: Mapping[str, Any]
    progress: Any
    record_date: date | None
    event: CorporateActionEvent | None
    unknown: tuple[str, ...]


def _day(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"日期格式无效: {value!r}")
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError(f"比例或现金数值无效: {value!r}")
    return float(number)


def descriptor_from_row(row: Mapping[str, Any], *, table: str,
                        file_sha256: str) -> ActionDescriptor:
    """复核抽取器原始行哈希，T 是唯一总权益比例，B/C 只留证。"""
    clean = {key: value for key, value in row.items() if key != "_row_hash"}
    digest = hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False,
                                       allow_nan=False).encode()).hexdigest()
    if digest != row.get("_row_hash"):
        raise ValueError(f"{table}/{row.get('id')}: row_hash 不匹配")
    if table not in ("dividend", "right_issue"):
        raise ValueError("不支持的来源表")
    identity = f"{table}:{row['id']}:{digest}"
    code = str(row["证券代码"])
    record = _day(row.get("股权登记日"))
    unknown: list[str] = ["implementation_not_certified", "known_at_unknown"]
    event = None
    if table == "right_issue":
        unknown.append("rights_no_subscription_coverage_unknown")
    else:
        ex = _day(row.get("除权除息日"))
        cash, total = _number(row.get("每股派息税前")), _number(row.get("每股送转"))
        bonus = _number(row.get("每股送股比例"))
        capital = _number(row.get("每股转增比例"))
        if total is None and (bonus or capital):
            unknown.append("total_ratio_missing")
        if cash is None:
            unknown.append("cash_amount_unknown")
        if cash:
            unknown.append("cash_tax_unknown")
        if total or bonus or capital:
            unknown.extend(("share_tax_unknown", "fractional_rule_unknown"))
        if ex is None:
            unknown.append("ex_date_missing")
        else:
            event = CorporateActionEvent(
                event_id=identity, instrument_id=code,
                kind="capitalization" if total or bonus or capital else "cash_dividend",
                source_table=table, source_row_id=str(row["id"]),
                source_snapshot_hash=file_sha256, source_version="sqlite_export_v2",
                record_date=record, ex_date=ex, pay_date=_day(row.get("派息日")),
                listing_date=_day(row.get("红股上市日")), gross_cash_per_share=cash,
                share_ratio=total, announced_date=_day(row.get("公告日期")),
            )
    return ActionDescriptor(identity, code, table, file_sha256,
                            MappingProxyType(dict(row)), row.get("方案进度"),
                            record, event, tuple(unknown))


@dataclass(frozen=True)
class CorporateActionSnapshot:
    """已核三个输入文件的冻结快照，manifest 自身只计算实测哈希。"""

    descriptors: tuple[ActionDescriptor, ...]
    file_sha256: Mapping[str, str]
    manifest_sha256: str
    metadata: Mapping[str, Any]

    @property
    def provider(self) -> CorporateActionProvider:
        return CorporateActionProvider(tuple(item.event for item in self.descriptors
                                             if item.event is not None))

    def evidence(self) -> dict[str, Any]:
        return {"file_sha256": dict(self.file_sha256),
                "manifest_sha256": self.manifest_sha256,
                "manifest_self_hash_trusted": False,
                "metadata": dict(self.metadata),
                "coverage": [{"event_id": item.event_id, "source_table": item.source_table,
                              "file_sha256": item.file_sha256, "raw_row": dict(item.raw_row),
                              "unknown": list(item.unknown)} for item in self.descriptors]}


def load_corporate_action_snapshot(root: str | Path, *,
                                   manifest_path: str | Path | None = None,
                                   expected_manifest_sha256: str | None = None,
                                   ) -> CorporateActionSnapshot:
    """校验 manifest core_data 的预期 SHA；可额外钉住外部提供的 manifest SHA。"""
    root = Path(root)
    manifest_bytes = (Path(manifest_path) if manifest_path else
                      root / "delivery_manifest_v4.json").read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 is not None and manifest_hash != expected_manifest_sha256:
        raise ValueError("manifest SHA256 不匹配")
    manifest = json.loads(manifest_bytes)
    payloads, hashes = {}, {}
    for name in ("dividend_range_rows.json", "right_issue_range_rows.json", "metadata_snapshot.json"):
        relative = f"task2_v2/{name}"
        content = (root / relative).read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != manifest["core_data"][relative]["sha256"]:
            raise ValueError(f"{relative}: SHA256 不匹配")
        hashes[relative] = digest
        payloads[name] = json.loads(content)
    descriptors = []
    seen: set[str] = set()
    for table, name in (("dividend", "dividend_range_rows.json"),
                        ("right_issue", "right_issue_range_rows.json")):
        for row in payloads[name]:
            source_id = f"{table}:{row['id']}"
            if source_id in seen:
                raise ValueError(f"来源 ID 重复: {source_id}")
            seen.add(source_id)
            descriptors.append(descriptor_from_row(
                row, table=table, file_sha256=hashes[f"task2_v2/{name}"]))
    return CorporateActionSnapshot(tuple(descriptors), MappingProxyType(hashes), manifest_hash,
                                   MappingProxyType(payloads["metadata_snapshot.json"]))
