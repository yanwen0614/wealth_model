# Checkpoint NumPy scalar 兼容修复计划

## 目标

在不改动 W2 权重、训练产物、超参数或训练结果的前提下，修复共享 checkpoint loader 对已保存 numpy scalar 的安全加载兼容，并保证新旧格式、Trainer 收尾与 walk-forward 信号入口兼容。

## 已知现状与决策

- `training/checkpoint.py` 使用 `torch.load(weights_only=True)`；Trainer 与信号 writer 均调用 `load_model_state`。
- W2 权重 pickle 包含 `numpy._core.multiarray.scalar`、`numpy.dtype` 与 `_codecs.encode` GLOBAL；裸 state_dict 对照不含这些 GLOBAL。
- 暂不降级为任意 pickle。先定位对象完整路径和 W1/W2 差异，再以真实失败夹具验证最小受限 allowlist 或原生化保存方案。
- W2 checkpoint SHA256：`03625b7d85e31c6982c04471a7243d4cd701d1edc55b643e97f0abf4391ef4a4`；原文件保持只读。

## 步骤

1. 在私有 Python 3.12 环境完整复现；定位 NumPy scalar 的 payload 路径/写入来源并比较可加载 W1 checkpoint。
2. 先新增 RED 测试：真实格式失败夹具、未知对象拒绝、新旧格式兼容、完整 strict state dict、Trainer 元信息及信号 writer 加载。
3. 实施单一最小修复；记录支持的 PyTorch/NumPy 版本与安全边界。
4. 仅执行指定单测、ruff、pyright；在真实 W2 文件验加载、参数/epoch/config，并复核 SHA256。
5. 冻结文件 SHA、diff、TDD 和验证证据，更新交付报告，等待主会话独立 QA。

## 边界

不训练、不读取 W2 收益/IC/标签结果、不生成完整信号、不改 W2 或其他 worktree/环境/锁文件，不提交或推送。
