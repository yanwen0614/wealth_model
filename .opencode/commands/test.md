---
description: 运行测试 - 执行 lint (ruff) + typecheck (pyright) + unittest（quant-model 兼容 cnn-harness 验证部分）
---

独立运行三项自动化验证，等同于 quant-model（兼容 cnn-harness）Quality Gate 的验证部分（Part B）。

## 执行步骤

### 1. 执行 Lint 检查

```bash
ruff check .
```

- 通过：输出 "All checks passed" 或退出码 0
- 失败：展示 error 列表

### 2. 执行 TypeCheck 检查

```bash
pyright
```

- 通过：0 errors
- 失败：展示 error 列表

### 3. 执行 Unit Test

默认 fast 档为冒烟测试，按 `test_scope` 分流：

```bash
# smoke / fast（默认，保存后即时 sanity，无网络依赖）
uv run python -m pytest -q
uv run python -m unittest -v

# 指定路径
uv run python -m pytest tests/test_parquet_dataset.py -v
uv run python -m unittest data.test.test_parquet_dataset -v

# parquet 冒烟：限制 code 数量快速验证数据链路
uv run python -m pytest tests/ -k parquet --max_codes 10 -q

# full（升级档，tmux 后台，会话 cnn_qa_full，输出 /tmp/opencode/qa_test_full_output.txt）
tmux new-session -d -s cnn_qa_full -c "$PWD" \
  "uv run python -m pytest > /tmp/opencode/qa_test_full_output.txt 2>&1; echo EXIT_CODE=\$? >> /tmp/opencode/qa_test_full_output.txt"
sleep 60 && tmux capture-pane -t cnn_qa_full -p | tail -40
tmux kill-session -t cnn_qa_full
```

- 通过：所有测试 PASS
- 失败：展示 FAIL/ERROR 列表
- full 档升级触发条件见 harness SKILL「测试选择策略」
- **场景→档位完整决策表见 `tests/AGENTS.md` 或 `data/test/AGENTS.md`「何时跑什么测试」**

### 4. 输出汇总报告

```
## 测试验证报告

| 检查项 | 结果 | 详情 |
|--------|------|------|
| Lint (ruff) | ✅ PASS / ❌ FAIL | {error 数量} errors |
| TypeCheck (pyright) | ✅ PASS / ❌ FAIL | {error 数量} errors |
| Unit Test | ✅ PASS / ❌ FAIL | {pass}/{total} passed |

VERDICT: PASS / FAIL
```

### 5. 可选：运行特定测试

如果用户指定了测试路径：
```bash
uv run python -m pytest {test_path} -v
uv run python -m unittest {test_path} -v
```

### 6. 可选：运行数据校验

如果用户关注数据链路冒烟：
```bash
uv run python -m data.parquet_dataset --max_codes 10 --dry-run
```

## 注意事项

- 三项全过才算 PASS，任一 FAIL 即整体 FAIL
- 如有 lint error，可建议用户执行 `ruff check --fix` 自动修复
- fast 档测试超时（>120s）视为 FAIL；full 档以输出文件 `EXIT_CODE=` 为完成判据，不按 120s 误判
