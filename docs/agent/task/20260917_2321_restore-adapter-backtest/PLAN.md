# 20260917_2321_restore-adapter-backtest Implementation Plan

> Generated: 2026-09-17 23:21 (UTC+8 假设)
> Task Dir: docs/agent/task/20260917_2321_restore-adapter-backtest

## Goal

重构坏合并的 `scripts/run_backtest.py` 为自洽文件，恢复 cnn_adapter 为回测唯一 CLI 路径，
并把 rolling 分支的回测新特性（指数基准/逐笔费用/target 语义/strong_buy）移植到 adapter 路径。

## Architecture

以 915116b 的 adapter 默认形态（`run_adapter_rolling/main/parse_args/logger/--parquet/--ohlc 告警`）
为骨架，以 rolling 分支的费用常量与指数/target 新参为血肉：CLI 只组装 adapter 调用，
target 语义下沉为 `order_strategy.py` 新外层策略类经 `runner.py` 接线，`backtest/engine.py`
降为纯函数库只被单测引用。`market.py`（parquet 直读）不动。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 费用 buy/sell→CostConfig 映射 | **用户决策（2026-09-17）：修改 `../backtest-core` 使 core 支持买卖拆分**（CostConfig 加买/卖佣金字段，后向兼容旧 `commission_rate`；core 引擎消费新字段；core 单测跟随）。跨仓任务 T00 先行，T04 依赖其字段 | 假设 A（max+要求相等） | 用户明确要求改 core；静默丢一边不可接受，max 近似同样丢精度 |
| 费用默认值差异 | CLI 默认沿用 engine 口径（buy/sell/stamp 各 0.00025，min 5.0），不跟 core 默认 0.0002/0.0005 | 跟 core 默认 | 回测结论连续性优先；core 默认差异在 PLAN 留痕防误读 |
| target 策略位置 | **用户决策（2026-09-17）：新文件 `backtest/cnn_adapter/target_strategy.py`**（`CnnTargetOrderStrategy` 独立文件；排序/预算逻辑与旧策略复用方式由 T03 定：抽公共小模块或方法级复用，禁止大段复制） | 同文件 | 用户选择旧文件不动，新策略独立演进 |
| engine CLI 解线后 test_engine 去留 | 保留 `tests/unit/backtest/test_engine.py` 不动（纯库测试继续过） | 删除 | 决策 d 明确 engine 作纯函数库保留；删测试等于删契约 |
| CLI 内 run_legacy_* 去留 | 删除 `run_legacy_rolling/run_target_mode(legacy 体)/run_legacy_regression` 的 CLI 侧函数，保留 `backtest/legacy.py` 守卫 | CLI 保留 legacy opt-in 双通道 | 决策 a“CLI 只留 adapter”+ 决策 d“legacy.py 保留”是文件级分工：守卫留在库，CLI 不再提供旧入口；否则 N01“默认 adapter”与 opt-in 并存，路由永不收口 |
| N01/N02 改/留 | N01：adapter 默认/路由/smoke 留（改 import 与 `--parquet` 断言）；legacy isolation 三例随 CLI 删除而删或改跳过；N02：legacy marked 两例删，`--ohlc` 告警两例留（改走新 CLI），adapter smoke 留，target 按新 adapter target 重写 | 全留 | 旧断言引用已删除的 `run_legacy_rolling/run_target_mode(legacy)`，留即红；清单由 T07 执行精确改/删 |
| CLI 单测改/留 | `test_run_backtest_cli.py`：fee/index/helpers/cost_rate 废弃/strong_buy CLI 默认留（改 `--ohlc` 为 `--parquet`）；`TestTargetMetricsStrongBuy`（mock `run_backtest_target` 的 legacy 体）按新 adapter target 重写 | 全留 | 现行 target metrics 测试 mock 的是 engine 直调体，新路径走 adapter 策略+runner，断言对象已变 |
| uv.lock 修复验证 | 删 148 行 `]` 后以 `tomllib.load` 为准 + `git diff` 仅一行动；`uv sync` 仅在离线可行时试跑 | 直接跑全量 uv sync | `uv.lock` 修好前 uv 全挂（需求 e）；以最小验证恢复 CLI 流水线，不阻塞于网络 |
| `--ohlc/--full_ohlc/--cost_rate` 参数 | 保留为废弃参数：显式传入告警忽略（`--ohlc/full_ohlc` 默认路径忽略，`--cost_rate` 恒忽略） | 直接删除参数 | 存量脚本/`run_eval_full.sh` 旧命令与单测仍传这些 flag；删参即 crash，告警忽略最平滑 |

## Impact

| 模块 | 文件 | 操作(create/modify) | 风险等级 |
|------|------|--------------------|----------|
| repo | `uv.lock` | modify（-1 行） | low |
| scripts | `scripts/run_backtest.py` | modify（重写 ~250 行） | high |
| backtest | `backtest/cnn_adapter/order_strategy.py` | modify（+~120 行） | high |
| backtest | `backtest/cnn_adapter/runner.py` | modify（+~60 行） | high |
| scripts | `scripts/run_eval_full.sh` | modify（~10 行） | low |
| tests | N01/N02/CLI 三文件 | modify | medium |

## Task Decomposition

### T00: backtest-core 支持买卖拆分佣金（跨仓）
- **文件**: `../backtest-core`（`CostConfig` 加买/卖佣金字段，后向兼容旧 `commission_rate`；引擎消费；core 单测跟随）
- **描述**: 用户决策改 core。字段设计由执行者定（推荐 `commission_rate_buy/sell` 可选，缺省回退 `commission_rate`），core 内所有 `CostConfig(...)` 构造点保持兼容；core 自有单测全过。
- **依赖**: 无（与 T01/T02 并行）
- **验收标准**: core 仓库单测全过；旧单字段构造行为不变（后向兼容断言）
- **need_test**: true（core 仓单测）

### T01: uv.lock 非法字符修复
- **文件**: `uv.lock` (modify，删 148 行 `]`)
- **描述**: 删除坏合并残留的多余 `]`，恢复合法 TOML。验证以标准库 TOML 解析为准。
- **依赖**: 无
- **预估行数**: -1
- **验收标准**: `tomllib.load(open('uv.lock','rb'))` 通过；`git diff uv.lock` 仅一行动
- **风险因子**: 行号漂移则按 `[package.metadata.requires-dev]` 闭合括号定位，不碰依赖版本
- **need_test**: TOML 解析（非单测）

### T02: CLI 重构为 adapter 唯一路径
- **文件**: `scripts/run_backtest.py` (modify，重写 ~250 行)
- **描述**: 以 915116b 为骨架重建自洽文件：恢复 `run_cnn_backtest` import、
  `logger`、`--parquet/--ohlc 告警/--legacy 删除` 的 main 路由；删除 engine ohlc rolling 体
  （`load_ohlc/benchmark_nav/run_backtest` CLI 引用）与 CLI 侧 legacy 体；保留
  `load_preds/load_full_ohlc?（仅 adapter target 若需则留）/save_holdings_csv` 按新设计取舍。
  本任务先立自洽骨架，指数/费用/target 增量由 T04–T05 叠加。
- **依赖**: T01
- **预估行数**: +250/-200
- **验收标准**: `import scripts.run_backtest` 无 NameError；`entry.logger` 存在；
  `--mode rolling --parquet` 走 adapter；`--ohlc` 仅 warning
- **风险因子**: MISTAKES 未载入（无 MISTAKES.md 路径传入）；误删 `load_index_close` 等 rolling 好函数则 T05 返工
- **need_test**: N01/N02 adapter 路由断言（T07）

### T03: adapter target 外层策略类（新文件）
- **文件**: `backtest/cnn_adapter/target_strategy.py` (create，~120 行) + 新单测文件
- **描述**: 新建 `CnnTargetOrderStrategy`（用户决策：新文件，旧 `order_strategy.py` 一字不动）：T 日全截面按 exp_ret 排名；
  持有 rank>target_size+sell_buffer 卖出（或 exit_on_nonpositive 且 exp_ret<=exit_threshold 卖出）；
  买入带 rank<=target_size 内 exp_ret<stro ng_buy_threshold（>0 时）跳过留现金不补位；
  float 股数等权（预算口径对标 engine `capital/target_size`，经 core 现金单折算整手）。
  与旧策略共享的排序逻辑抽小函数复用，禁止大段复制。
- **依赖**: T02（CLI–策略接口约定先定）
- **预估行数**: +120
- **验收标准**: 买入带/卖出带/exit/strong_buy 四语义单测；旧策略单测全过
- **风险因子**: core 整手/锁定裁决与 engine `limit_up` 跳过口径差 → 在策略注释显式声明以 core 为准
- **need_test**: 新增策略单测 + `test_cnn_adapter_orders.py` 回归

### T04: runner 费用透传 + 策略选择
- **文件**: `backtest/cnn_adapter/runner.py` (modify，+~60 行)
- **描述**: `run_cnn_backtest` 新增可选参（`cost_config` 或买/卖/印花/最低佣金四元组 + `strategy`
  选择 rolling/target 及 target 四参），默认走旧 rolling 行为；`CostConfig` 按 Key Decisions
  假设 A 组装；`PortfolioConfig(top_n/target_size/sell_buffer)` 按模式组装；新参进 `config_hash`。
- **依赖**: T03
- **预估行数**: +60
- **验收标准**: 默认调用与旧行为一致；费用/策略参数进 hash；整段核验仍通过
- **风险因子**: `commission_rate` 默认 0.0002 与 CLI 0.00025 差 → 显式透传覆盖，不依赖 core 默认
- **need_test**: runner 参数透传单测 + `test_cnn_adapter_smoke.py` 回归

### T05: CLI 指数基准 + 费用/废弃参数
- **文件**: `scripts/run_backtest.py` (modify，T02 后的增量 +~80 行)
- **描述**: 移植 rolling 好版本：`load_index_close/index_covers_trade_days/benchmark_index_nav`
 （指数默认 000300.SH，缺文件 raise、无交集告警跳过）；费用五参
  (`--capital/--buy_rate/--sell_rate/--stamp_rate/--min_commission`) 透传 runner；
  `--cost_rate/--ohlc/--full_ohlc` 保留为废弃告警忽略；target CLI 四参
  (`--target_size/--sell_buffer/--exit_on_nonpositive/--exit_threshold/--strong_buy_threshold`) 接策略。
- **依赖**: T04（费用接口）；与 T03 可部分并行
- **预估行数**: +80
- **验收标准**: 指数/费用/strong_buy CLI 单测对齐；`--cost_rate` 显式仅告警
- **风险因子**: `benchmark_index_nav(index_dates, index_close, trade_days)` 为指数版签名，
  勿与旧 `benchmark_nav(c, d, ohlc)` 混淆
- **need_test**: `test_run_backtest_cli.py` 改后断言

### T06: run_eval_full.sh Step2 切换
- **文件**: `scripts/run_eval_full.sh` (modify，~10 行)
- **描述**: Step 2 切 `--parquet "$PARQUET"` adapter 命令（`$PARQUET` 第 4 参已存在）；
  删 `--ohlc "$OHLC"`；`OHLC` 变量仅 Step 1 保留或清理以 sh 实际为准。
- **依赖**: T02
- **预估行数**: ~10
- **验收标准**: Step 2 无 `--ohlc`；`bash -n` 通过
- **风险因子**: Step 1 仍产 OHLC 路径表 → 仅 Step 2 不消费，不删 Step 1
- **need_test**: `bash -n` + CLI smoke（由执行侧跑）

### T07: 单测改/留对齐
- **文件**: `tests/unit/backtest/test_n01_entry_switch.py` (modify)、
  `tests/unit/backtest/test_n02_integration.py` (modify)、
  `tests/unit/scripts/test_run_backtest_cli.py` (modify)、
  `tests/unit/backtest/test_engine.py` (不动)
- **描述**: N01 legacy isolation 随 CLI 删除而删/跳过，adapter 路由留；N02 legacy marked 删、
  `--ohlc` 告警留、target 按 adapter 重写；CLI target-metrics 按新路径重写；engine 不动。
- **依赖**: T02, T03, T04, T05, T06
- **预估行数**: +80/-120
- **验收标准**: 改后三文件与新 CLI 对齐；`test_engine.py` 零修改仍过
- **风险因子**: N02 现行 target 用例含已删除的 `min_edge/edge_tail_pct`（c7e8f72 已删）→ 一并清理
- **need_test**: 本任务即测试对齐

## execution_order

T00 ∥ T01 → T02 → (T03 → T04 → T05) ∥ (T06) → T07。其中 T06 仅依赖 T02 可与 T03–T05 并行；
T04 依赖 T00（core 字段）+ T03；T05 依赖 T04 接口，T03 与 T05 可部分并行（策略语义先定，CLI 接线后合）。
T00 在 ../backtest-core 仓执行，改动单独 commit（不混入 cnn 仓）。
