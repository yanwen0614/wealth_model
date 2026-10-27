# 独立 QA 审查清单

- [x] 根因有完整异常复现；明确 NumPy scalar 的 payload 键路径、创建来源及 W1 对照证据。
- [x] 修复只允许必要的 NumPy scalar/dtype 类型；未引入 `weights_only=False` 自动回退。
- [x] 测试覆盖的未知自定义类由 weights_only 拒绝；不将此夹具扩大表述为任意恶意输入保证。
- [x] 真实失败夹具修复前RED、修复后GREEN；覆盖裸 state_dict 与当前 dict checkpoint。
- [x] strict载入401个张量键、dtype和值一致；epoch/config元信息固定。
- [x] writer路径测试覆盖旧NumPy lr格式；尚未生成完整W2信号。
- [x] 目标W1/W2原权重加载成功，SHA256前后不变，safe_globals上下文恢复。
- [x] 主会话在私有venv实际跑25+58测试、Ruff、目标Pyright；writer测试24项既有告警与主区基线对照一致；无W2环境或锁文件更改。
- [x] 交付包含冻结SHA/TDD/命令和版本边界；独立Luna安全语义QA已PASS，报告路径见HARNESS_PROGRESS。
