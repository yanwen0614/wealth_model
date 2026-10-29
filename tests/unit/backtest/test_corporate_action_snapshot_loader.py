"""冻结原始公司行动输入的定向验证。"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backtest.cnn_adapter.corporate_action_snapshot_loader import (
    descriptor_from_row,
    load_corporate_action_snapshot,
)


def raw_row(**changes):
    row = {"id": 1, "证券代码": "A.SZ", "方案进度": "3",
           "每股送转": 0.3, "每股送股比例": 0.1, "每股转增比例": 0.2,
           "每股派息税前": 0.18, "股权登记日": 20210511,
           "除权除息日": 20210512, "派息日": 20210513, "红股上市日": 20210514}
    row.update(changes)
    row["_row_hash"] = hashlib.sha256(json.dumps(
        row, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return row


class SnapshotLoaderTest(unittest.TestCase):
    def test_total_ratio_once_and_raw_evidence(self):
        row = raw_row()
        item = descriptor_from_row(row, table="dividend", file_sha256="frozen")
        assert item.event is not None
        self.assertEqual(item.event.share_ratio, 0.3)
        self.assertEqual(item.event.gross_cash_per_share, 0.18)
        self.assertIsNone(item.event.bonus_tax_rule)
        self.assertEqual(item.raw_row, row)
        self.assertEqual(item.progress, "3")
        self.assertIn("share_tax_unknown", item.unknown)

    def test_missing_ex_keeps_unresolved_record(self):
        item = descriptor_from_row(raw_row(除权除息日=None),
                                   table="dividend", file_sha256="frozen")
        self.assertIsNone(item.event)
        assert item.record_date is not None
        self.assertEqual(item.record_date.isoformat(), "2021-05-11")
        self.assertIn("ex_date_missing", item.unknown)

    def test_bad_row_hash_rejected(self):
        row = raw_row()
        row["每股送转"] = 0.9
        with self.assertRaisesRegex(ValueError, "row_hash"):
            descriptor_from_row(row, table="dividend", file_sha256="frozen")

    def test_no_c_fallback_and_rights_coverage_only(self):
        item = descriptor_from_row(raw_row(每股送转=None), table="dividend", file_sha256="x")
        assert item.event is not None
        self.assertIsNone(item.event.share_ratio)
        self.assertIn("total_ratio_missing", item.unknown)
        rights = descriptor_from_row(raw_row(), table="right_issue", file_sha256="x")
        self.assertIsNone(rights.event)
        self.assertIn("rights_no_subscription_coverage_unknown", rights.unknown)

    def test_manifest_checks_files_and_ignores_bad_self_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "task2_v2").mkdir()
            core_data = {}
            for name, payload in (("dividend_range_rows.json", [raw_row()]),
                                  ("right_issue_range_rows.json", []),
                                  ("metadata_snapshot.json", {"mode": "ro"})):
                content = json.dumps(payload, ensure_ascii=False).encode()
                relative = f"task2_v2/{name}"
                (root / relative).write_bytes(content)
                core_data[relative] = {"sha256": hashlib.sha256(content).hexdigest()}
            manifest = {"core_data": core_data, "documentation": {
                "delivery_manifest_v4.json": {"sha256": "已知错误的自引用"}}}
            (root / "delivery_manifest_v4.json").write_text(json.dumps(manifest), encoding="utf-8")
            snapshot = load_corporate_action_snapshot(root)
            self.assertEqual(len(snapshot.provider.events), 1)
            self.assertFalse(snapshot.evidence()["manifest_self_hash_trusted"])
            self.assertEqual(snapshot.evidence()["metadata"], {"mode": "ro"})
            with self.assertRaisesRegex(ValueError, "manifest SHA256"):
                load_corporate_action_snapshot(root, expected_manifest_sha256="错误的外部哈希")
            (root / "task2_v2/dividend_range_rows.json").write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA256"):
                load_corporate_action_snapshot(root)
