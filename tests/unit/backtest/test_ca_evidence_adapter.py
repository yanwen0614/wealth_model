"""严格限域证据绑定；非官方fixture仅验证真实core接线。"""
import inspect
import json
import unittest
from tempfile import TemporaryDirectory

from scripts import run_2025_restricted as entry
from tests.unit.backtest.test_2025_restricted_fix3 import ORIGINAL, publication_probe

OUT = entry.TEMP / "validation_2025_ca_evidence_adapter_20261029"


def fixture_files(root, *, role="FINAL_EXPLICIT_NO_DISTRIBUTION", until="2025-01-13"):
    changes = {"id": 900001, "证券代码": "000001.SZ", "分红年度": 20241231,
        "公告日期": 20250102, "预案公告日": None, "_evidence_fixture_only": True}
    raw = {k: v for k, v in ORIGINAL[103185].raw_row.items() if k != "_row_hash"}
    raw.update(changes)
    body = json.dumps(raw, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    row_sha = entry.hashlib.sha256(body).hexdigest()
    source = root / "fixture_source.json"
    source.write_bytes(body)
    raw["_row_hash"] = row_sha
    item = entry.descriptor_from_row(raw, table="dividend", file_sha256=row_sha)
    text = "证券代码000001.SZ；2024年度；公告日期2025-01-02；正式决定：不派发现金红利，不送红股，不以公积金转增股本。"
    document = {"security": "000001.SZ", "proposal_period": "20241231", "publication_date": "2025-01-02",
                "document_role": role, "text": text}
    evidence = root / "synthetic_document.fixture"
    evidence.write_bytes(b"EVIDENCE_FIXTURE_ONLY\n" + json.dumps(document, ensure_ascii=False).encode())
    payload = {"schema_version": 1, "event_id": item.event_id, "security": item.instrument_id,
        "source_row_sha256": row_sha, "proposal_period": "20241231", "action": "NO_CASH_NO_BONUS_NO_CAPITALIZATION",
        "source_path": str(source), "source_sha256": entry.sha(source), "evidence_path": str(evidence),
        "evidence_sha256": entry.sha(evidence), "publication_date": "2025-01-02", "document_role": role,
        "valid_from": "2025-01-03", "valid_until": until, "quote": text}
    manifest = root / "fixture_binding.json"
    entry.save(manifest, payload)
    return manifest, payload, changes, item


class EvidenceClosureTests(unittest.TestCase):
    def test_synthetic_document_does_not_unlock_default_core_guard(self):
        with TemporaryDirectory(dir=OUT) as tmp:
            root = entry.Path(tmp)
            manifest, payload, changes, _ = fixture_files(root)
            payload["approved"] = True
            entry.save(manifest, payload)
            report = publication_probe(root / "default_guard", changes=changes)
            self.assertIsNotNone(report["error"])
            self.assertFalse(report["main_return_usable"])
            self.assertGreater(report["terminal_positions"].get("000001.SZ", 0), 0)
            self.assertGreater(report["terminal_locked"].get("000001.SZ", 0), 0)

    def test_evidence_bypass_api_is_not_implemented(self):
        self.assertNotIn("evidence_adapter", inspect.signature(entry.run_restricted).parameters)
