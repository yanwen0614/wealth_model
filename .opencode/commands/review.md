---
description: 代码审查 - 对指定文件或最近变更执行质量关卡审查（quant-model 兼容 cnn-harness）
---

触发 quant-model skill（兼容 cnn-harness 别名），以 `review_only` 模式执行审查。

## 执行步骤

### 1. 确定审查范围

根据用户输入确定审查的文件范围：

| 用户输入 | 审查范围 |
|---------|---------|
| 指定了文件路径 | 只审查指定文件 |
| 未指定文件 | 审查 `git diff --name-only HEAD` 中的变更文件 |
| 指定了模块名 | 审查该模块下最近变更的文件 |

### 2. 读取约束文件

- `CLAUDE.md`
- 目标模块 `AGENTS.md`（如存在）

### 3. 执行 Quality Gate

派遣 `quality-gate` 子代理（mode=review_verify），一次性完成审查与验证。

**6 道质量关卡审查**：
1. 规范一致性
2. 模块边界
3. 数据安全
4. 导入合规
5. 错误处理
6. 性能风险

**三项验证**：
1. `ruff check .`
2. `pyright`
3. 按 `test_scope`（fast/full）执行单元测试：默认 fast 前台直跑 `uv run python -m pytest -q` 或 `uv run python -m unittest`；命中「测试选择策略」触发条件升级 full 时走 tmux 后台跑全量 `uv run python -m pytest`（cnn 全量含 parquet_dataset 冒烟 `--max_codes 10`）

### 4. 输出审查报告

```
## 代码审查报告

### 审查范围
| 文件 | 操作 |
|------|------|
| ... | ... |

### Quality Gate 结果 — 质量关卡
| 关卡 | 结果 | Issues |
|------|------|--------|
| 规范一致性 | PASS/FAIL | ... |
| 模块边界 | PASS/FAIL | ... |
| 数据安全 | PASS/FAIL | ... |
| 导入合规 | PASS/FAIL | ... |
| 错误处理 | PASS/FAIL | ... |
| 性能风险 | PASS/FAIL | ... |

### Quality Gate 结果 — 三项验证
| 检查项 | 结果 | 详情 |
|--------|------|------|
| Lint | PASS/FAIL | ... |
| TypeCheck | PASS/FAIL | ... |
| Test | PASS/FAIL | ... |

### 总结
VERDICT: PASS / FAIL

{如有 FAIL，列出需要修复的 issues 及建议}
```
