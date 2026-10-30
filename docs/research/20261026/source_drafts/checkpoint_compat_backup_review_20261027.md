# 窄范围独立只读复核报告 — checkpoint NumPy 兼容

**审查者**：DeepSeek V4 Flash（备援 + only 只读不编码）
**主会话证据源**：`checkpoint_main_verification_results_20261027.md`（已读）
**本树私有 .venv**：6 个 checkpoint tests 实际重跑，其余引用主会话

---

## 文件冻结 SHA 核验

| 文件 | 本树 SHA | 用户给定 |
|---|---|---|
| `training/checkpoint.py` | f1ac2f5c60... | ✓ f1ac2f5c60c5f135...db56082 |
| `tests/unit/training/test_training_checkpoint.py` | 24f0f17220... | ✓ 24f0f1722065e69c...ed0fa5 |
| `training/trainer.py` | 5c6b9c1175... | - |
| `tests/unit/scripts/test_walkforward_signals.py` | 4a23ffa4e4... | - |

当前 HEAD: `7db4062 build: 同步固定股数限价接口wheel与schema身份`（build 提交，不影响训练层）

---

## 6 个 checkpoint tests 实际重跑结果

```
Ran 6 tests in 3.418s
OK
```

全部通过，无新失败。

---

## 4 点逐项核查

### 1. weights_only=True + allowlist 是否覆盖 W2 旧 numpy.lr 且拒未知类

**PASS**

- `training/checkpoint.py:40-44` `_NUMPY_SAFE_GLOBALS` = 三项：
  - `multiarray.scalar`（NumPy 2.x 走 `numpy._core.multiarray`，1.x 回退 `numpy.core.multiarray`）
  - `np.dtype`
  - `type(np.dtype(np.float64))`
- `load_checkpoint()`（L116-117）硬编码 `weights_only=True`，**无任何降级路径**（旧 `TypeError` try/except 已删除）。低于 PyTorch 2.6 直接 `RuntimeError` — 这是设计决定，非缺陷。
- `test_unknown_checkpoint_object_stays_rejected`（test 文件 L96-101）：`UnsupportedObject()` 自定义类被 `pickle.UnpicklingError` 拒绝 — **实测 PASS**。
- `test_legacy_numpy_float64_optimizer_lr_loads_with_weights_only`（L85-94）：构造 W2 同形旧 dict（`np.float64(3e-4)`），`load_checkpoint` 成功恢复 `np.float64` 类型 — **实测 PASS**。

**结论**：allowlist 仅放行三类型，不泛化到任意 numpy 对象，不降级 `weights_only`，自定义类被拒。W2 兼容验证通过。

### 2. safe_globals 上下文退出恢复 + native_scalars 不改变模型张量

**PASS**

- `training/checkpoint.py:52` 使用 `torch.serialization.safe_globals(...)` context manager — PyTorch 内置保证退出时恢复全局 allowlist。主会话验证（结果文档 L15）："safe_globals 上下文退出未污染全局 allowlist"。
- `_native_scalars()`（L56-66）：递归转换 `np.generic` → `.item()`（Python 原生标量），仅作用于 dict/list/tuple 容器。
- **调用位置**（L100-101）：只包裹 `optimizer.state_dict()` 和 `scheduler.state_dict()`；**模型 `state_dict()`（L99）不经过 `_native_scalars`**。模型张量、元数据、所有权重 dtype 不受影响。主会话 W1/W2 tensor equality + strict=True 验证通过（结果文档 L13-14）。

**结论**：上下文安全，模型张量不改，optimizer/scheduler 标量转换正确。

### 3. bare_state / dict / strict / newsave 兼容性边界

**PASS**

| 场景 | 机制 | 行号 | 说明 |
|---|---|---|---|
| **旧裸 state_dict** | `extract_state_dict` 无 `MODEL_KEY` 原样返回 + `UserWarning` | L124-126 | 仅评估不可续训 |
| **新 dict 格式** | `extract_state_dict` 返回 `obj[MODEL_KEY]` | L123 | 含 optimizer/scheduler/epoch/config |
| **strict=True** | 透传给 `model.load_state_dict(..., strict=strict)` | L133 | 默认 True，调用方可改 |
| **新保存文件** | `_native_scalars` 转换 optimizer/scheduler 中 NumPy 标量 | L100-101 | 新文件不再携带 numpy 全局对象 |
| **旧文件加载** | `_numpy_safe_globals` 放行已有 NumPy 标量 | L116-117 | W2 兼容 |

**PyTorch 下限说明**：`training/checkpoint.py:51` 显式 `RuntimeError("checkpoint 安全兼容要求 PyTorch >= 2.6")`；`training/checkpoint.py:112-113` docstring 明确 "仅支持 PyTorch >=2.6"。无隐秘降级。

**NumPy 下限说明**：`training/checkpoint.py:33-37` 注释 "项目依赖下限为 NumPy 2.4"（对应 `_core.multiarray` 路径），同时保留 `numpy.core.multiarray` 兼容路径（numpy < 2 回退）。无 numpy 1.x 依赖风险。

### 4. Pyright 24 错误基线

**PASS**（基于主会话证据，本审查不再重跑全仓 Pyright）

- 主会话验证（结果文档 L11-12）：`checkpoint.py` + `test_training_checkpoint.py` = **0 errors**。`test_walkforward_signals.py` = **24 errors**。
- 基线对比：对主区同文件（`D:/code/cnn_full_20260905/cnn/...`）运行同一私解释器亦为 **24 errors**，错误内容一致。
- 新增 fixture：`UnsupportedObject`（test 文件 L20-21）为无方法纯类，不触发 Pyright 新错。`_rewrite_as_legacy_numpy_lr_checkpoint`（signals 文件 L93-103）为纯过程函数，不触发新错。

**结论**：24 错误系基线既有，改动新增行零新错。符合 "不宣称全仓零告警" 约定。

---

## 整体判定

**PASS** — 4 项均无真实缺陷。checkpoint.py 的 `_NUMPY_SAFE_GLOBALS` allowlist 设计正确（scalar/dtype/float64 dtype），scope 不膨胀；`_native_scalars` 不侵入模型权重；新旧格式兼容路径明确；Pyright 基线无新错；6 test 全部通过。
