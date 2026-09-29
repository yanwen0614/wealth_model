"""T14 RED: checkpoint 存 dict{model,optimizer,scheduler,epoch,config} + 旧裸 state_dict 兼容加载。"""
import json
import os
import tempfile
import unittest

import torch


def _tiny_model():
    return torch.nn.Sequential(torch.nn.Flatten(), torch.nn.Linear(8 * 4, 6))


def _tiny_opt(model):
    return torch.optim.AdamW(model.parameters(), lr=1e-3)


class TestCheckpointRoundtrip(unittest.TestCase):
    def test_save_dict_and_reload_state(self):
        from training.checkpoint import extract_state_dict, load_checkpoint, save_checkpoint
        model = _tiny_model()
        opt = _tiny_opt(model)
        sched = torch.optim.lr_scheduler.StepLR(opt, step_size=1)
        cfg = {"EPOCHS": 2, "LEARNING_RATE": 1e-3, "NORMALIZE": "relative"}
        tmp = os.path.join(tempfile.mkdtemp(), "best_model.pth")
        save_checkpoint(tmp, model, opt, sched, epoch=1, config=cfg)
        obj = load_checkpoint(tmp, map_location="cpu")
        self.assertIn("model", obj)
        self.assertIn("optimizer", obj)
        self.assertIn("scheduler", obj)
        self.assertEqual(obj["epoch"], 1)
        json.dumps(obj["config"])  # config 必须 json 可序列化
        model2 = _tiny_model()
        model2.load_state_dict(extract_state_dict(obj))

    def test_legacy_bare_state_dict_loads(self):
        from training.checkpoint import extract_state_dict, load_checkpoint
        model = _tiny_model()
        tmp = os.path.join(tempfile.mkdtemp(), "legacy.pth")
        torch.save(model.state_dict(), tmp)  # 旧格式：裸 state_dict
        obj = load_checkpoint(tmp, map_location="cpu")
        model2 = _tiny_model()
        model2.load_state_dict(extract_state_dict(obj))
        for p1, p2 in zip(model.parameters(), model2.parameters()):
            self.assertTrue(torch.equal(p1, p2))

    def test_scheduler_state_continues(self):
        from training.checkpoint import load_checkpoint, save_checkpoint
        model = _tiny_model()
        opt = _tiny_opt(model)
        sched = torch.optim.lr_scheduler.StepLR(opt, step_size=1)
        sched.step()  # last_epoch=1
        tmp = os.path.join(tempfile.mkdtemp(), "sched.pth")
        save_checkpoint(tmp, model, opt, sched, epoch=0, config={})
        obj = load_checkpoint(tmp, map_location="cpu")
        opt2 = _tiny_opt(_tiny_model())
        sched2 = torch.optim.lr_scheduler.StepLR(opt2, step_size=1)
        sched2.load_state_dict(obj["scheduler"])
        self.assertEqual(sched2.last_epoch, sched.last_epoch)


if __name__ == "__main__":
    unittest.main()
