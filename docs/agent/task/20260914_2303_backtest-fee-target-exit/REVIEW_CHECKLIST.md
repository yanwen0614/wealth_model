# 审查清单 — backtest-fee-target-exit

> 生成时间：2026-09-14 23:03
> 依据：需求「回测口径升级（真实费用模型 + target 退出规则）」，全部选项已确认

## 需求理解

把 rolling 与 target 两种回测的费用模型由单一 `cost_rate` 一次性扣减，升级为 A 股真实费用模型：
- 买入佣金 = `max(买入成交额×0.00025, 5.0)`；卖出佣金 = `max(卖出成交额×0.00025, 5.0)`，
  另加印花税 = `卖出成交额×0.00025`（卖出总费用 = 佣金 + 印花税）。
- 单笔净收益 = `(卖出成交额 − 卖出总费用 − (买入成交额 + 买入佣金)) / (买入成交额 + 买入佣金)`。
- 组合本金 `capital` 默认 1,000,000 元，用于折算最低佣金；NAV 仍以 1 起点，费用/成交额按 `capital` 折算。
- target 退出：`sell_buffer` 默认 200→500；新增 `--exit_on_nonpositive`（默认关）按 `exp_ret≤exit_threshold`
  （默认 0.0）卖出，与 rank buffer 规则互斥。

### 显式假设（实现时按此执行）

1. 佣金按成交额（不含费用）计；最低 5 元按每笔买/卖各自独立判定。
2. 印花税仅卖出单边；过户费等其它费用不建模。
3. `exit_on_nonpositive` 开启时忽略 `sell_buffer`；持仓在该日截面无 exp_ret（缺预测）→ 不卖（保守）。
4. `capital` 仅用于最低佣金折算，不改变 NAV 单位收益比（NAV 恒 1 起点）。
5. `--cost_rate` 保留仅兼容，显式传入 warning 后忽略，不影响结果。
6. 默认 `capital=1e6` 且 `target_size=100` 时 target 单槽预算 10000 < 阈值 20005 → 默认命中最低佣金（预期）。
7. `weight` 字段仍记 `1/target_size`（信息字段，不参与费用）。
8. benchmark 与策略使用同一费用模型（否则超额口径不一致）。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|---|---|---|---|
| 回测引擎 | backtest/engine.py | 新增/修改 | 费用常量/纯函数；rolling `_simulate`/`run_backtest`/`benchmark_nav`；target 买入求解/`_close_holding`/退出规则 |
| 回测导出 | backtest/__init__.py | 修改 | 补充 `run_backtest_target` 与费用常量导出（可选） |
| 回测 CLI | scripts/run_backtest.py | 修改 | 新增本金/费率/退出参数；`--cost_rate` deprecate；metrics 字段 |
| 评估脚本 | scripts/run_eval_full.sh, scripts/run_eval_pipeline.py | 修改 | 去 `--cost_rate 0.0015`；docstring 同步 |
| 脚本文档 | scripts/README.md | 修改 | run_backtest 选项表补新参数 |
| 测试 | tests/unit/backtest/test_engine.py, tests/unit/scripts/test_run_backtest_cli.py | 新增/修改 | 费用数值、rolling/target 手算、退出规则、capital 敏感性、CLI |
| 进度 | docs/agent/task/.../HARNESS_PROGRESS.md | 修改 | 端到端新旧对比 |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 处置 |
|---|---|---|---|
| `cost_rate` | 是 | engine.py / run_backtest.py / run_eval_full.sh / run_eval_pipeline.py / test_engine.py | 全部迁移到新费用模型，CLI 侧 deprecate |
| `commission`/`stamp`/`capital`/`本金`/`佣金`/`印花税` | 否 | — | 新增，无重复实现 |
| `_simulate` | 是 | backtest/engine.py:64 | 改签名接入逐笔费用 |
| `benchmark_nav` | 是 | backtest/engine.py:150 | 改用同一费用模型 |
| `_close_holding` | 是 | backtest/engine.py:195 | 改费用模型 + entry_cost 基数 |
| `sell_buffer` | 是 | engine.py:203,252 / run_backtest.py:188 / test_engine.py | 默认 200→500 |
| `net_return`/`trade_net`/`_commission` | 否 | — | 新增纯函数 |
| target 退出规则 | 否（仅 rank buffer） | engine.py:252 | 新增 `exit_on_nonpositive`/`exit_threshold` |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 命名常量全大写（`BUY_COMMISSION_RATE` 等）；函数 docstring/类型注解；line-length 120；中文注释 | HIGH |
| 2 | 模块边界 | 费用模型仅在 `backtest/engine.py`；`scripts/*` 只做参数透传不重实现公式；不侵入 data/models/training/criterion | HIGH |
| 3 | 数据安全 | 无硬编码凭证；不读 parquet；`capital>0`、费率 `>=0`、`min_commission>=0` 输入校验 | HIGH |
| 4 | 导入合规 | 无通配符 import；无未使用 import；`warnings` 按需 import | MEDIUM |
| 5 | 错误处理 | 非法 capital/rate raise；`--cost_rate` deprecate 明确 warning 不静默；`budget≤min_commission` 跳过买入不崩溃 | MEDIUM |
| 6 | 性能风险 | `_simulate` 保持 O(n_days×N) 纯标量运算，无全量矩阵复算；target 每槽常数次标量运算，无 O(N²) | MEDIUM |
| 7 | 费用口径一致性 | rolling/target/benchmark 三处共用同一纯函数；`ret_net` 与 NAV 路径同模型；印花税仅卖出单边 | HIGH |

## 费用数值校验点

| # | 校验点 | 输入 | 期望 |
|---|--------|------|------|
| 1 | 买入最低佣金生效 | 买额 10000 | 佣金 `5.0` |
| 2 | 买入费率生效 | 买额 100000 | 佣金 `25.0` |
| 3 | 最低佣金边界 | 买额 20000 | 佣金 `5.0`（20000×rate=5.0） |
| 4 | 卖出佣金+印花税 | 卖额 110000 | 佣金 `27.5` + 印花税 `27.5` = `55.0` |
| 5 | 卖出最低佣金 | 卖额 10000 | 佣金 `5.0` + 印花税 `2.5` |
| 6 | 净收益（rate 生效） | 买 100000 / 卖 110000 | `(110000−55−100025)/100025 ≈ 0.0991752` |
| 7 | 净收益（min 生效） | 买 10000 / 卖 11000 | `(11000−7.75−10005)/10005 ≈ 0.0986756` |
| 8 | 最低佣金阈值 | `B*=5×(1+0.00025)/0.00025` | `20005.0`；`budget<B*` 用 `(budget−5)/px`，否则 `budget/(px×(1+buy_rate))` |
| 9 | rolling 单票买额 | capital=1e6, horizon=5, N=1, nav=1 | `(1/5/1)×1e6 = 200000` |
| 10 | target 默认命中最低佣金 | capital=1e6, target_size=100 | 单槽 budget `10000 < 20005` → 佣金 `5.0` |
| 11 | target 费率生效 | capital=1e6, target_size=2, px=10 | 单槽佣金 `≈124.97`；`nav[1]=0.99975` |
| 12 | capital 敏感性 | capital 1e6 vs 4e4（target_size=2） | 单槽佣金 `≈124.97`（rate） vs `5.0`（min） |
| 13 | 印花税单边 | 买入 | 无印花税；仅卖出计 |
| 14 | 端到端可复现 | 同 preds 同参数两次运行 | NAV 逐位一致（`np.testing.assert_array_equal`） |
