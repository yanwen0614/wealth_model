"""T18 RED: logs 轮转 dry-run（最小失败测试，只删超限 run_*，KEEP/当次永不删）。"""
import os
import tempfile
import unittest

from log_manager import collect_rotation_plan, prune_old_runs


def _mk_run(root: str, name: str, mtime: float) -> str:
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "training.log"), "w", encoding="utf-8") as f:
        f.write("x")
    os.utime(path, (mtime, mtime))
    return path


class TestLogRotationDryRun(unittest.TestCase):
    def test_count_overflow_lists_oldest_and_deletes_nothing(self):
        """超 keep_last_n 时 dry-run 列出最老，且不删除任何目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            olds = [_mk_run(tmp, f"run_2026090{i}_000000", 1000 + i) for i in range(1, 4)]
            with tempfile.TemporaryDirectory() as tmp2:  # 隔离 mtime 基准
                _ = tmp2
            plan = collect_rotation_plan(tmp, keep_last_n=2, max_total_bytes=10**12)
            self.assertEqual(plan["delete"], [olds[0]])
            self.assertEqual(sorted(plan["keep"]), sorted(olds[1:]))
            for p in olds:  # dry-run 不删
                self.assertTrue(os.path.isdir(p))

    def test_keep_dir_never_candidate(self):
        """KEEP 永不进入待删（即使最老/超限）。"""
        with tempfile.TemporaryDirectory() as tmp:
            keep = os.path.join(tmp, "KEEP")
            os.makedirs(os.path.join(keep, "baseline"), exist_ok=True)
            os.utime(keep, (1, 1))
            olds = [_mk_run(tmp, f"run_2026090{i}_000000", 1000 + i) for i in range(1, 4)]
            plan = collect_rotation_plan(tmp, keep_last_n=1, max_total_bytes=10**12)
            self.assertNotIn(keep, plan["delete"])
            for p in plan["delete"]:
                self.assertNotIn("KEEP", p)
            self.assertTrue(os.path.isdir(keep))
            _ = olds

    def test_exclude_current_never_deleted(self):
        """当次运行目录（exclude）永不进入待删；dry_run=False 仍保留。"""
        with tempfile.TemporaryDirectory() as tmp:
            r1 = _mk_run(tmp, "run_20260901_000000", 1000)
            r2 = _mk_run(tmp, "run_20260902_000000", 2000)
            cur = _mk_run(tmp, "run_20260903_000000", 3000)
            plan = prune_old_runs(tmp, keep_last_n=1, max_total_bytes=10**12,
                                  exclude=cur, dry_run=True)
            self.assertNotIn(cur, plan["delete"])
            self.assertIn(r1, plan["delete"])
            plan2 = prune_old_runs(tmp, keep_last_n=1, max_total_bytes=10**12,
                                   exclude=cur, dry_run=False)
            self.assertTrue(os.path.isdir(cur))
            self.assertTrue(os.path.isdir(r2) or not os.path.isdir(r1))
            self.assertNotIn(cur, plan2["delete"])

    def test_volume_overflow_evicts_oldest(self):
        """体积超限时从最老逐出（KEEP/当次仍豁免，dry-run 不删）。"""
        with tempfile.TemporaryDirectory() as tmp:
            olds = [_mk_run(tmp, f"run_2026090{i}_000000", 1000 + i) for i in range(1, 4)]
            plan = collect_rotation_plan(tmp, keep_last_n=10, max_total_bytes=1)
            self.assertEqual(sorted(plan["delete"]), sorted(olds[:2]))
            self.assertEqual(plan["keep"], [olds[2]])
            for p in olds:
                self.assertTrue(os.path.isdir(p))


if __name__ == "__main__":
    unittest.main()
