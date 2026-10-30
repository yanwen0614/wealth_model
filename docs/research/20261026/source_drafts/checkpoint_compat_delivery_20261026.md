# Checkpoint NumPy compatibility 冻结交付

日期：2026-10-27　分支：`openchamber/checkpoint-numpy-compat-20261026`　状态：待主会话独立 QA；未提交。

## 根因与最小修复

W2 `best_model.pth` 的 `optimizer.param_groups[0].lr` 是 `numpy.float64`。W2 config scheduler=`CosineWarmup`；`training/factory.py` 的 lambda 在余弦段返回 `np.cos(...)` 的 NumPy scalar，AdamW state 与 scheduler `_last_lr` 随 checkpoint 保存。原 `torch.load(weights_only=True)` 报 `Unsupported global: GLOBAL numpy._core.multiarray.scalar`。

`training/checkpoint.py`：新保存前递归将 optimizer/scheduler state 的 `np.generic` 转原生 Python scalar；旧文件继续 `weights_only=True`，只在 `safe_globals` 上下文允许 NumPy scalar 构造器、`numpy.dtype` 和 float64 dtype。未使用 `weights_only=False`。PyTorch 默认已允许 `_codecs.encode`：去掉自定义放行后 W2 仍可载入，故未加入 allowlist。逐项剔除测试显示：缺少 scalar/dtype 支持会拒绝 W2；未知自定义类仍以 `pickle.UnpicklingError` 拒绝。删除了旧 Torch 不支持 safe_globals 时的非安全回退，要求 PyTorch≥2.6。

## W1/W2 只读对比

| 项目 | W1 | W2 |
|---|---|---|
| 路径 | `D:/code/cnn_full_20260905/cnn/logs/relative/run_20261026_100509/best_model.pth` | `C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/w2-f4-training-20261026/logs/relative/run_20261026_212052/best_model.pth` |
| SHA256（前后不变） | `a1e35967234aeaf8463bebe6ec823cbd3a2ac240e9b55a778808588c90a56cde` | `03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4` |
| epoch / optimizer lr | 1 / Python `float` | 5 / `numpy.float64` |
| pickle NumPy GLOBAL | 无 | scalar、dtype、`_codecs.encode` |
| strict 模型键 | 401，匹配 | 401，匹配 |

两份 checkpoint 外层格式与训练配置相同：`SEQ_LEN=60`、`HORIZON=10`、`NORMALIZE=relative`、`LABEL_MODE=excess`、`LEARNING_RATE=0.0003`、`scheduler=CosineWarmup`。W2 `load_model_state(strict=True)` 返回 epoch 5；逐键比较 401 个模型 tensor，全部 `torch.allclose(atol=0, rtol=0)`；config 与 checkpoint 中原 config 相同；SHA 前后完全一致。未读取 W1 training.log 或信号文件，也未读取 W2 收益/IC/标签结果。

## TDD 与验证

- RED：新增 NumPy lr checkpoint 测试后、修复前，单测完整报错 `WeightsUnpickler error: Unsupported global: GLOBAL numpy._core.multiarray.scalar`；真实 W2 同样复现。
- GREEN：5 个 checkpoint 单测通过（新格式原生化、旧 NumPy float64 格式、裸 state_dict、dict strict 元信息、拒绝未知对象）。
- 信号 writer：`tests.unit.scripts.test_walkforward_signals` 19 项通过；F4 writer fixture 使用旧 dict + NumPy float64 optimizer lr，不生成 W2 信号。
- 最小 CI 门：58 项通过。Ruff 全仓通过。目标 Pyright（checkpoint.py + checkpoint tests）0 errors；全仓 Pyright 当前报告 879 errors，主要在既有动态 dataset/test 类型推断及其他模块，本次未修范围外错误。
- 私有 worktree `.venv` 独立复制 W2 venv（`robocopy /E /XJ`，无 junction；源未修改）：Python 3.12、torch 2.12.0+cu130、NumPy 2.5.2、CUDA 13.0 可用。
- 不训练、不运行完整信号、不提交。`git diff --check` 通过；lock 文件未变更。

## 可复现命令

```powershell
& '.venv/Scripts/python.exe' -m unittest tests.unit.training.test_training_checkpoint tests.unit.scripts.test_walkforward_signals -v
& '.venv/Scripts/python.exe' -m unittest tests.unit.test_ci_gate tests.unit.data.test_identity tests.unit.data.test_transform_kernel tests.unit.training.test_training_preprocessing tests.unit.data.test_dataset_cache
& 'C:/Users/yanwen/AppData/Local/Temp/opencode/checkpoint-compat-venv/Scripts/ruff.exe' check .
& '.venv/Scripts/python.exe' -m pyright --pythonpath '.venv/Scripts/python.exe' training/checkpoint.py tests/unit/training/test_training_checkpoint.py
& '.venv/Scripts/python.exe' -m pyright --pythonpath '.venv/Scripts/python.exe'
& '.venv/Scripts/python.exe' 'C:/Users/yanwen/AppData/Local/Temp/opencode/verify_w2_ckpt.py'
```

## 版本边界与代码 SHA256

项目运行边界 PyTorch≥2.6（需 `weights_only` + `safe_globals`），NumPy≥2.4；实际验证 torch 2.12.0+cu130 / NumPy 2.5.2。NumPy 1.x 导入分支保留但不在项目依赖支持范围，未单独验证。

| 文件 | SHA256 |
|---|---|
| `training/checkpoint.py` | `F1AC2F5C60C5F135E30F9350E5556E56FF430D72E4AD9E771650AD494DB56082` |
| `training/trainer.py`（仅 Ruff import 排序） | `5C6B9C1175B018E36591B3B5D92B16CA4CBF282E776C31BE07E570DE8E93BAA4` |
| `tests/unit/training/test_training_checkpoint.py` | `24F0F1722065E69CA965B8863F38E9251C49D9285DA4053EF7941978AEED0FA5` |
| `tests/unit/scripts/test_walkforward_signals.py` | `4A23FFA4E4F01564BE7BE81A0E7CE93D817E80CFF48AFB3584F02F8C5C9482A7` |

原 `docs/agent/task/20261026_checkpoint-numpy-compat/` 的三份 harness 文档（PLAN / REVIEW_CHECKLIST / HARNESS_PROGRESS）已于 2026-10-31 随任务目录精简删除，其哈希不再可校验；结论见 `docs/agent/task/agent_task_conclusions.md` §5，过程原文可查 git 历史。

变更 diff：4 个代码/测试文件，`112 insertions(+), 11 deletions(-)`；另有 3 个 harness 任务文档。保持冻结，等待主会话安排独立 Luna QA。
