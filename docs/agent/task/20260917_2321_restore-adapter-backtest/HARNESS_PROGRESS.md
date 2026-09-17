# 进度跟踪 — 20260917_2321_restore-adapter-backtest

> 生成时间：2026-09-17 23:21 (UTC+8 假设)
> 需求：恢复 cnn_adapter 为回测唯一 CLI 路径，并移植 rolling 分支回测新特性（指数基准/费用透传/target 策略）
>
> 收口（2026-09-17）：T00–T07 全 done；QG VERDICT=PASS（120 例全过，2 MAJOR 已修：target 补 --parquet 校验+单测、bench assert；6 MINOR 留痕）；cnn commit 待推送，core T00 三文件单独 commit

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T00 | core 支持买卖拆分佣金（跨仓） | done | PASS | ../backtest-core 三文件，684 例过，单独 commit |
| T01 | uv.lock 非法字符修复 | done | PASS | 删 148 行多余 `]`，TOML 解析验证 |
| T02 | CLI 重构为 adapter 唯一路径 | done | PASS | 依赖 T01；重写 run_backtest.py 自洽 |
| T03 | adapter target 外层策略类 | done | PASS | 依赖 T02（接口约定）；order_strategy.py |
| T04 | runner 费用透传 + 策略选择 | done | PASS | 依赖 T03；runner.py 扩展 |
| T05 | CLI 指数基准 + 费用/废弃参数 | done | PASS | 依赖 T04；与 T03 可部分并行 |
| T06 | run_eval_full.sh Step2 切换 | done | PASS | 依赖 T02；独立小改 |
| T07 | 单测改/留对齐 | done | PASS | 依赖 T02–T06；N01/N02/CLI 改，engine 留 |

## 执行详情

### T01: uv.lock 非法字符修复
- **状态**：done
- **依赖**：无
- **文件**：
  - `uv.lock` (modify，-1 行)
- **预估行数**：-1
- **验收标准**：`tomllib.load(open('uv.lock','rb'))` 通过；`git diff uv.lock` 仅删 148 行 `]`
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T02: CLI 重构为 adapter 唯一路径
- **状态**：done
- **依赖**：T01
- **文件**：
  - `scripts/run_backtest.py` (modify，重写 ~250 行)
- **预估行数**：+250/-200
- **验收标准**：`import scripts.run_backtest` 无 NameError；默认 rolling 走 adapter；
  `--ohlc` 告警忽略；engine ohlc rolling 不在 CLI；`logger` 恢复
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T03: adapter target 外层策略类
- **状态**：done
- **依赖**：T02
- **文件**：
  - `backtest/cnn_adapter/target_strategy.py` (create 新文件，用户决策，~197 行)
- **预估行数**：+120
- **验收标准**：新策略类实现买入带/卖出带/exit/strong_buy 语义；旧 `CnnOrderStrategy` 语义不变
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T04: runner 费用透传 + 策略选择
- **状态**：done
- **依赖**：T03
- **文件**：
  - `backtest/cnn_adapter/runner.py` (modify，+~60 行)
- **预估行数**：+60
- **验收标准**：`run_cnn_backtest` 接费用 + 策略选择参数；默认调用与旧行为一致；config_hash 覆盖新参
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T05: CLI 指数基准 + 费用/废弃参数
- **状态**：done
- **依赖**：T04（费用透传接口）；与 T03 可部分并行
- **文件**：
  - `scripts/run_backtest.py` (modify，含于 T02 后续增量，+~80 行)
- **预估行数**：+80
- **验收标准**：指数默认 000300.SH，缺文件 raise、无交集跳过；`--cost_rate` 告警忽略
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T06: run_eval_full.sh Step2 切换
- **状态**：done
- **依赖**：T02
- **文件**：
  - `scripts/run_eval_full.sh` (modify，~10 行)
- **预估行数**：~10
- **验收标准**：Step 2 为 `--parquet "$PARQUET"` adapter 命令；无 `--ohlc`
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2

### T07: 单测改/留对齐
- **状态**：done
- **依赖**：T02, T03, T04, T05, T06
- **文件**：
  - `tests/unit/backtest/test_n01_entry_switch.py` (modify)
  - `tests/unit/backtest/test_n02_integration.py` (modify)
  - `tests/unit/scripts/test_run_backtest_cli.py` (modify)
  - `tests/unit/backtest/test_engine.py` (不动，验证过)
- **预估行数**：+80/-120
- **验收标准**：N01/N02/CLI 按 PLAN 改/留清单对齐；test_engine 不动仍过
- **Quality Gate 结果**：PASS
- **修复轮次**：0/2
