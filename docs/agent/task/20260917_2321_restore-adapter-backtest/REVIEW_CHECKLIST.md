# 审查清单 — 20260917_2321_restore-adapter-backtest

> 生成时间：2026-09-17 23:21 (UTC+8 假设)
> 需求：恢复 cnn_adapter 为回测唯一 CLI 路径，移植 rolling 分支回测新特性，重构坏合并的 scripts/run_backtest.py

## 需求理解
- 现行 `scripts/run_backtest.py` 是坏合并：imports 为 rolling 分支新符号
  （`benchmark_index_nav/run_backtest/run_backtest_target`/费用常量 + `data.schema`），
  函数体残留 915116b（`run_adapter_rolling/run_legacy_rolling/run_legacy_regression`），
  引用未导入的 `run_cnn_backtest/guard_legacy_disabled/LegacyBacktestDisabledError/`
  `mark_legacy_result/benchmark_nav/logger` → 13 处 NameError/AttributeError（静态分析结论，不执行测试）。
- 锁定决策（不得更改；有疑问以 `status: blocked` 上报，不猜）：
  a. CLI 只留 adapter；`--mode rolling` 默认走 adapter（`--parquet` 直读真实 OHLC）；
     engine ohlc rolling 从 CLI 删除；`--ohlc` 默认路径只告警忽略。
  b. target 在 adapter 内实现为新外层交易策略类（对标 engine `run_backtest_target` 语义）。
  c. adapter rolling 追加指数基准（默认 000300.SH）+ 费用透传到 core `CostConfig`；
     `--cost_rate` 废弃告警忽略。
  d. `backtest/engine.py` 纯函数库保留（`test_engine.py` 继续过），只与 CLI 解线；
     `backtest/legacy.py` 的 `guard_legacy_disabled + run_legacy_regression`（恒拒绝）保留。
  e. `uv.lock:148` 多余 `]` 删除，恢复合法 TOML。
  f. `scripts/run_eval_full.sh` Step 2 切 `--parquet` adapter 路径。
- 显式假设（blocked 候选，见 PLAN Key Decisions）：费用 buy/sell→`CostConfig` 单一费率映射、
  target 策略文件位置、CLI 内 `run_legacy_*` 去留与 N01/N02 改/留清单。

## 影响范围
| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| scripts | `scripts/run_backtest.py` | modify（重写~250行） | 删 engine ohlc rolling/legacy 体，留 adapter rolling+target+指数+费用透传 |
| backtest | `backtest/cnn_adapter/order_strategy.py` | modify（+~120行） | 新增 target 策略类（买入带/卖出带/strong_buy/费用感知在 runner 侧） |
| backtest | `backtest/cnn_adapter/runner.py` | modify（+~60行） | `run_cnn_backtest` 扩展接费用 + 策略选择（默认保持旧签名兼容） |
| backtest | `backtest/engine.py` | 不动 | 纯函数库保留，只与 CLI 解线 |
| backtest | `backtest/legacy.py` | 不动 | guard + regression 恒拒绝保留 |
| scripts | `scripts/run_eval_full.sh` | modify（~10行） | Step 2 切 `--parquet` adapter 路径，删 `--ohlc` |
| repo | `uv.lock` | modify（删1行） | 删 148 行多余 `]` |
| tests | `tests/unit/backtest/test_n01_entry_switch.py` | modify | legacy/adapter 路由断言按新 CLI 改 |
| tests | `tests/unit/backtest/test_n02_integration.py` | modify | legacy marked/--ohlc 告警/target 按新设计改 |
| tests | `tests/unit/scripts/test_run_backtest_cli.py` | modify | 费用/指数/strong_buy 按 adapter CLI 改/留 |
| tests | `tests/unit/backtest/test_engine.py` | 不动 | 纯库测试，保持过 |

## 重复检测
| 搜索关键词 | 是否存在 | 位置/复用结论 |
|------------|---------|---------------|
| `run_cnn_backtest` | 是 | `backtest/cnn_adapter/runner.py` 复用，不重实现 |
| `CnnOrderStrategy` | 是 | `order_strategy.py` 保留；target 新增类，不改旧语义 |
| `benchmark_index_nav/load_index_close/index_covers_trade_days` | 是 | engine/rolling 分支已有实现 → 移植到 adapter CLI，不在 adapter 内重写 |
| `CostConfig/PortfolioConfig/ExecutionConfig` | 是 | `backtest_core.contracts.config` 实测为准（见 PLAN 费用映射表） |
| `benchmark_nav`（旧全截面基准） | 是（engine） | CLI 不再引用，随 engine ohlc rolling 一并从 CLI 删除 |
| `run_legacy_rolling/run_legacy_regression` | 残留 | CLI 侧删除；`legacy.py` 守卫 + 恒拒绝保留 |
| `g9_observed_mask/55/48` | 无关 | 本需求不碰特征维度，禁止借机改 data/models 层 |

## 质量关卡
| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | ruff line-length 120；`logger = logging.getLogger(__name__)` 恢复；无通配符 import | HIGH |
| 2 | 模块边界 | engine 只被 tests import、不被 CLI import；adapter 不读 ohlc npz；data/training 不动 | HIGH |
| 3 | 数据安全 | 无硬编码凭证；指数缺文件显式 FileNotFoundError；无区间交集告警跳过基准 | HIGH |
| 4 | 导入合规 | 删除未用 import（`benchmark_nav/run_backtest/run_backtest_target/费用常量` 按需取舍）；`run_cnn_backtest/guard/mark/logger` 引用全部有定义 | MEDIUM |
| 5 | 错误处理 | `--parquet` 缺失显式 ValueError；`--cost_rate` 显式告警忽略；target 负阈值由策略/CLI raise | MEDIUM |
| 6 | 性能风险 | adapter 逐日订单循环无 O(N²) 全量扫描；parquet 直读经 `CnnMarketDataProvider` 不全量进内存 | MEDIUM |

## adapter/费用映射/指数基准核验项
- [ ] `import scripts.run_backtest` 无 NameError；`entry.logger/run_cnn_backtest` 存在
- [ ] `--mode rolling --parquet X` 走 `run_adapter_rolling`；`--ohlc` 仅 warning 忽略
- [ ] 费用：CLI `--buy_rate/--sell_rate/--stamp_rate/--min_commission/--capital` →
      core `CostConfig(commission_rate/min_commission/stamp_tax_rate)` 映射与 PLAN 一致（含默认值差异说明）
- [ ] target：买入带 rank<=target_size；卖出带 rank>target_size+sell_buffer 或
      exit_on_nonpositive 且 exp_ret<=exit_threshold；strong_buy>0 跳过留现金不补位；float 股数等权
- [ ] 指数：默认 `000300.SH`；`load_index_close` 缺文件 raise；无交集告警跳过基准与超额
- [ ] `backtest/engine.py` 零 CLI 引用；`test_engine.py` 仍过；`legacy.py` 未动
- [ ] `uv.lock`：`python -c "import tomllib; tomllib.load(open('uv.lock','rb'))"` 通过；`uv sync --offline --dry-run`（如离线可行）
- [ ] `run_eval_full.sh` Step 2 为 `--parquet "$PARQUET"` adapter 命令，无 `--ohlc`
