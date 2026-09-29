"""T05 RED: LoggerManager 防碰撞 + config.json 原子写（最小失败测试）。"""
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from log_manager import LoggerManager


class TestLoggerManagerCollision(unittest.TestCase):
    def test_same_second_two_managers_get_different_dirs(self):
        """同秒启动两次必须得不同 run_* 目录（递增后缀）。"""
        with tempfile.TemporaryDirectory() as tmp:
            fixed = datetime(2026, 9, 28, 12, 0, 0)  # noqa: DTZ001 - 与生产 run 目录本地 wall time 契约对齐
            with mock.patch("log_manager.datetime") as mock_dt:
                mock_dt.now.return_value = fixed
                m1 = LoggerManager(log_dir=tmp, config={"a": 1})
                m2 = LoggerManager(log_dir=tmp, config={"a": 2})
            self.assertNotEqual(m1.run_log_dir, m2.run_log_dir)
            self.assertTrue(os.path.isdir(m1.run_log_dir))
            self.assertTrue(os.path.isdir(m2.run_log_dir))

    def test_failed_save_leaves_no_half_written_config(self):
        """kill 模拟：序列化失败时旧 config.json 必须保持完整有效（无半写）。"""
        with tempfile.TemporaryDirectory() as tmp:
            m = LoggerManager(log_dir=tmp, config={"ok": True})
            cfg_path = os.path.join(m.run_log_dir, "config.json")
            with open(cfg_path, encoding="utf-8") as f:
                before = f.read()
            json.loads(before)  # 前置：首次写入有效
            m.config = {"bad": object()}  # json.dumps 必抛 TypeError
            with self.assertRaises(TypeError):
                m._save_config()
            with open(cfg_path, encoding="utf-8") as f:
                after = f.read()
            self.assertEqual(before, after)
            json.loads(after)  # 仍为有效 JSON，无半写截断


if __name__ == "__main__":
    unittest.main()
