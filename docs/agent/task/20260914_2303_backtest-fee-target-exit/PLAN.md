# backtest-fee-target-exit 实施计划

> 生成时间：2026-09-14 23:03
> Task Dir: `docs/agent/task/20260914_2303_backtest-fee-target-exit/`
> 分支：`feature/rolling-normalization-cnn`
> 需求类型：feature（回测口径升级：真实费用模型 + target 退出规则）

## Goal

把 rolling 与 target 两种回测的费用模型由「单一 `cost_rate` 一次性扣减」升级为 A 股真实费用模型
（买入佣金万2.5 最低 5 元；卖出佣金万2.5 最低 5 元 + 印花税万2.5），并以组合本金 `capital`
（默认 1,000,000 元）驱动最低佣金折算；同时给 target 模式增加可配退出规则
（`sell_buffer` 默认 200→500，新增 `--exit_on_nonpositive`/`--exit_threshold`）。

## Architecture

- `backtest/engine.py` 集中新增费用纯函数（`_commission`/`net_return_after_fees`）与命名常量；
  rolling 的 `_simulate`/`run_backtest`/`benchmark_nav` 与 target 的买入求解/`_close_holding`
  全部改走同一逐笔费用模型；NAV 始终 1 起点，成交额/费用按 `capital` 折算回 NAV 单位。
- target 买入改为「求解 `shares` 使 `shares×px + buy_commission = budget`」，
  `budget=(nav_pre/target_size)×capital`；最低佣金分两情形，阈值 `B*=MIN_COMMISSION×(1+buy_rate)/buy_rate≈20005`。
- target 退出新增开关 `exit_on_nonpositive`（默认关）：开启时按 `exp_ret ≤ exit_threshold`（默认 0.0）卖出，
  关闭时沿用 rank buffer；`sell_buffer` 默认由 200 改为 500。
- `scripts/run_backtest.py` 暴露 `--capital/--buy_rate/--sell_rate/--stamp_rate/--min_commission/
  --exit_on_nonpositive/--exit_threshold`；旧 `--cost_rate` 保留但 deprecate（warning 后忽略）。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 理由 |
|---|---|---|---|
| 买入费用 | `max(买额×buy_rate, MIN_COMMISSION)` | 单边固定 cost_rate | A 股佣金有最低 5 元 |
| 卖出费用 | `max(卖额×sell_rate, MIN_COMMISSION) + 卖额×stamp_rate` | 佣金含印花税一并 | 印花税单边卖出、无最低 |
| 单笔净收益 | `(卖额−卖佣−印花税−买额−买佣)/(买额+买佣)` | `(1+g)(1−c)/(1+c)−1` | 以实际成本基数为分母 |
| 本金口径 | rolling 单票买额=`(nav/horizon/N)×capital`；target `budget=(nav_pre/target_size)×capital` | 固定 1 元名义 | 最低佣金需绝对金额 |
| NAV 记账 | NAV 1 起点；成交额/费用 `÷capital` 折算；target `cash` 以 NAV 单位 | shares 用 NAV 归一化 | 与现有 NAV 语义兼容 |
| 最低佣金分支 | `budget<20005` 用 `shares=(budget−5)/px`，否则 `budget/(px×(1+buy_rate))` | 只算 rate 情形 | 默认 target budget=10000 命中最低佣金 |
| 卖出规则 | `sell_buffer=500`；`exit_on_nonpositive` 时按 `exp_ret≤exit_threshold` | 两者叠加 | 需求要求互斥/可配 |
| benchmark | 与策略同一费用模型 | 保持旧 cost_rate | 否则 excess 口径失真 |
| `--cost_rate` | 保留参数 + warning + 忽略 | 直接删除 | 兼容 `run_eval_full.sh`/历史命令 |

## Impact

| 模块 | 文件 | 操作 | 风险 |
|---|---|---|---|
| 回测引擎 | backtest/engine.py | modify | high |
| 回测导出 | backtest/__init__.py | modify | low |
| 回测 CLI | scripts/run_backtest.py | modify | medium |
| 评估脚本 | scripts/run_eval_full.sh, scripts/run_eval_pipeline.py | modify | low |
| 脚本文档 | scripts/README.md | modify | low |
| 测试 | tests/unit/backtest/test_engine.py, tests/unit/scripts/test_run_backtest_cli.py | modify/create | medium |
| 进度 | docs/agent/task/20260914_2303_backtest-fee-target-exit/HARNESS_PROGRESS.md | modify | low |

> 风险：改 `engine.py` 费用模型影响 rolling 与 target 全部历史回测结果口径为 high；
> CLI/脚本参数兼容（`--cost_rate`）为 medium；纯文档/导出为 low。

## Task Decomposition

### T01 费用纯函数与命名常量
- **文件**: `backtest/engine.py` (modify)；`tests/unit/backtest/test_engine.py` (modify)
- **描述**: 新增 `BUY_COMMISSION_RATE=0.00025`、`SELL_COMMISSION_RATE=0.00025`、`STAMP_DUTY_RATE=0.00025`、
  `MIN_COMMISSION=5.0`、`DEFAULT_CAPITAL=1_000_000.0`；`_commission(amount, rate)=max(amount×rate, MIN_COMMISSION)`；
  `net_return_after_fees(buy_amount, sell_amount, *, buy_rate, sell_rate, stamp_rate, min_commission)` 返回单笔净收益。
- **依赖**: 无
- **预估行数**: +80
- **need_test**: 是
- **验收标准**: 买 10000→佣金 5.0（min 生效）；买 100000→25.0（rate）；卖 110000→佣 27.5+印花税 27.5=55.0；
  `net_return_after_fees(100000, 110000)==(110000−55−100025)/100025`；`net_return_after_fees(10000, 11000)==(11000−7.75−10005)/10005`。
- **风险因子**: 阈值边界 `amount=20000`（rate 恰为 5.0，max 取 5.0）须一致。

### T02 rolling 逐笔费用模型
- **文件**: `backtest/engine.py` (modify)；`tests/unit/backtest/test_engine.py` (modify)
- **描述**: `_simulate` 增 `capital`/费率参数；单票买额 `buy_amount=(nav[i]/horizon/len(rets))×capital`、
  卖额 `buy_amount×(1+g)`，逐笔算净收益后 `gain += invest_each_nav×net_return`；`run_backtest`/`benchmark_nav`
  增 `capital`+费率 kwargs；`holdings.ret_net` 用同一模型，名义额 `(1/horizon/len(picked))×capital`。
- **依赖**: T01
- **预估行数**: +120
- **need_test**: 是
- **验收标准**: `_synth(8,[("000001",0.10)])` topn=1 capital=1e6 → `nav[6]=1+0.2×((220000−110−200050)/200050)`；
  `benchmark_nav` 与手算一致；capital 小到使单票买额<20000 时最低佣金生效、不同 capital 结果不同。
- **风险因子**: `_simulate` 的 `len(rets)` 与 `run_backtest` 的 `len(picked)` 必须一致，否则名义额错配；
  benchmark 须与策略同模型。

### T03 target 逐笔费用模型
- **文件**: `backtest/engine.py` (modify)；`tests/unit/backtest/test_engine.py` (modify)
- **描述**: `run_backtest_target` 增 `capital`+费率参数；买入求解 `shares` 使 `shares×px + max(shares×px×buy_rate,5)=budget`
  （`budget=(nav_pre/target_size)×capital`，两情形阈值 20005，`budget≤5` 跳过）；`shares` 为实际股数，
  `cash`/`nav` 以 NAV 单位（`÷capital`）；`_close_holding` 返回卖出净额并记录 `entry_cost=shares×entry_px+buy_comm`，
  `ret_net=(卖额−卖佣−印花税−entry_cost)/entry_cost`。
- **依赖**: T01
- **预估行数**: +150
- **need_test**: 是
- **验收标准**: capital=1e6、target_size=2、px=10 → `shares=budget/(10×1.00025)`、`nav[1]=0.99975`（费用 249.94/1e6）；
  capital=40000、target_size=2 → 命中最低佣金 `shares=(20000−5)/10`、`nav[1]=0.99975`；平仓 `ret_net` 符合通式；
  capital 敏感性（1e6 vs 4e4）佣金一分位不同。
- **风险因子**: cash/nav 单位换算易漏 `÷capital`；预算在 20005 边界两情形须连续一致；强制末日平仓同样计费。

### T04 target 退出规则（sell_buffer=500 / exit_on_nonpositive）
- **文件**: `backtest/engine.py` (modify)；`tests/unit/backtest/test_engine.py` (modify)
- **描述**: `run_backtest_target` 的 `sell_buffer` 默认 200→500；新增 `exit_on_nonpositive=False`、
  `exit_threshold=0.0`；卖出选择改为：开启开关时卖出 `exp_map.get(s) ≤ exit_threshold` 的持仓，
  关闭时沿用 `rank_map.get(s,0) > target_size+sell_buffer`；两规则互斥（开关开启时忽略 rank buffer）。
- **依赖**: T03
- **预估行数**: +70
- **need_test**: 是
- **验收标准**: 默认签名 `sell_buffer==500`；`exit_on_nonpositive=True` 且 `exp_ret≤0` 时 T+1 open 卖出（持有天数缩短）；
  `exit_threshold=0.01` 时 `exp_ret=0.005` 也卖（可配）；关闭开关时 rank 决定卖出；缺预测持仓不误卖。
- **风险因子**: 决策日与执行日错位（T 日 `prev_dec` 决定、T+1 open 执行）不可破坏；`exp_map` 缺 key 语义需明确。

### T05 CLI/脚本/文档适配
- **文件**: `scripts/run_backtest.py` (modify)；`scripts/run_eval_full.sh` (modify)；`scripts/run_eval_pipeline.py` (modify)；
  `scripts/README.md` (modify)；`backtest/__init__.py` (modify)；`tests/unit/scripts/test_run_backtest_cli.py` (create)
- **描述**: CLI 增 `--capital`(default 1e6)/`--buy_rate`/`--sell_rate`/`--stamp_rate`/`--min_commission`/
  `--exit_on_nonpositive`(store_true)/`--exit_threshold`；`--sell_buffer` 默认 200→500；`--cost_rate` 改 default None，
  显式传入时 `warnings.warn` 后忽略；metrics.json/NOTE/打印/图题改记费用参数；`run_eval_full.sh` 去掉 `--cost_rate 0.0015`
  并更新注释；`run_eval_pipeline.py` docstring 去掉 `--cost_rate` 表述；README 表补新选项；`__init__` 补导出。
- **依赖**: T02, T03, T04
- **预估行数**: +130
- **need_test**: 是（CLI 默认值 + deprecated 警告）
- **验收标准**: `parse_args([]).capital==1_000_000.0`、`sell_buffer==500`、`exit_on_nonpositive is False`；
  `--cost_rate 0.0015` 触发 warning 且不改变结果；`run_eval_full.sh` 无 `--cost_rate`。
- **风险因子**: metrics.json 字段名变化若删旧键会破坏下游读 JSON 的工具（当前无），须保留 `mode`/`target_size` 等旧键。

### T06 全量单测 + ruff 收尾
- **文件**: `tests/unit/backtest/test_engine.py` (modify)、`tests/unit/**` 按需 (modify)
- **描述**: 修复因费用模型升级而失效的旧断言（原 `NET=1.1×0.9985−1`）；确保 `unittest discover` 全绿与 touched 文件 ruff 通过。
- **依赖**: T01–T05
- **预估行数**: +60
- **need_test**: 否（回归）
- **验收标准**: `uv run --project . python -m unittest discover tests/unit` 全绿；`ruff check` 对改动文件无错。
- **风险因子**: 遗漏隐式依赖旧 `cost_rate` 默认的断言。

### T07 端到端重跑与新旧对比
- **文件**: `docs/agent/task/20260914_2303_backtest-fee-target-exit/HARNESS_PROGRESS.md` (modify)
- **描述**: 用现有 6 臂 preds + `logs/ohlc_path_2026-01-01_2026-08-31.npz`（rolling）与
  `logs/ohlc_full_2026-01-01_2026-08-31.npz`（target）重跑；旧基线取 `logs/backtest_*/metrics.json`（rolling）
  与 `logs/backtest_target_e0e5_ts100/metrics.json`（target, buffer=200/cost=0.0015）；产出新旧对比表。
- **依赖**: T01–T06
- **预估行数**: +40（无生产代码）
- **need_test**: 是（端到端）
- **验收标准**: 6 臂 rolling（top5/10/20/50/100）与 target（size=100）新旧 annual/sharpe/超额对照表落 HARNESS_PROGRESS；
  新产物落 `logs/backtest_*_fee_*`；结论说明费用模型升级与 buffer/exit 规则各自的净值影响。
- **风险因子**: 旧结果口径不可比（必须显式标注 cost_rate/buffer 差异）；全市场 target 回测耗时且无并发。

## 风险与假设

### 风险
1. **旧结果不可比**：新费用模型（万2.5+印花税+最低5元）与 target 默认 `sell_buffer 500` 相对旧
   `cost_rate=0.0015`/`buffer=200` 是双变量变化，历史 metrics/记忆数字不得直接混用，E2E 必须显式新旧对照。
2. **`--cost_rate` 兼容**：保留参数但忽略，须明确 warning，避免 `run_eval_full.sh`/历史命令静默改变结果。
3. **最低佣金阈值分支**：`budget` 在 `B*≈20005` 边界两情形须连续一致；target 默认 `capital=1e6,size=100`
   → `budget=10000<B*`，默认命中最低佣金，测试须显式覆盖。
4. **benchmark 口径**：基准若不同模型则超额失真，必须与策略共用纯函数。
5. **单位换算**：target `shares` 为实际股数，`cash/nav` 需 `÷capital`，易漏；rolling `len(rets)` 与
   `len(picked)` 必须同名额度。
6. **E2E 资源**：全市场 target 回测无并发且耗时；`full_ohlc` 已存在（`logs/ohlc_full_2026-01-01_2026-08-31.npz`）。

### 显式假设
1. 佣金按成交额（不含费用）计；最低 5 元按每笔买/卖各自独立判定。
2. 印花税仅卖出单边；过户费等其它费用不建模。
3. `exit_on_nonpositive` 开启时忽略 `sell_buffer`；持仓在该日截面缺 `exp_ret` → 不卖（保守）。
4. `capital` 仅用于最低佣金折算，不改变 NAV 单位收益比（NAV 恒 1 起点）。
5. `--cost_rate` 显式传入 warning 后忽略，不影响结果；默认 None。
6. 默认 `capital=1e6` 且 `target_size=100` 时 target 单槽预算 10000<20005 → 默认命中最低佣金（预期行为）。
7. `weight` 字段仍记 `1/target_size`（信息字段，不参与费用）。
8. benchmark 与策略使用同一费用模型。
