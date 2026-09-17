# add-strong-buy-gate 实施计划

> 生成时间：2026-09-15 00:05
> Task Dir: `docs/agent/task/20260915_0005_add-strong-buy-gate/`
> 需求类型：feature（target 回测买入端新增「绝对预测收益」强买门槛）

## Goal

给 target 回测模式新增「强买门槛」`strong_buy_threshold`：仅当买入带（`rank <= target_size`）候选的
绝对预测收益 `exp_ret >= 阈值` 时才允许买入；不满足阈值者跳过该槽位、留现金、**不补位**。
默认 `0.0` = 关闭该规则（保证向后兼容），可扫描 1%/2%/3% 等档位，用于评估
「需模型给出较强上涨语义才买」对组合表现的影响，并与两套退出规则（`--sell_buffer 500` /
`--exit-on-nonpositive`）及 size 5/10/50 交叉测试。

## Architecture

- `backtest/engine.py` `run_backtest_target` 新增参数 `strong_buy_threshold: float = 0.0`，
  校验 `strong_buy_threshold < 0` 时 `raise ValueError`。买入循环内新增一个**纯预测**过滤分支：
  位置在既有 `min_edge` 过滤（`rank_map[s]/target_size > 1-edge_tail_pct and exp_map[s] < min_edge`）之后、
  OHLC 行查询 / 涨停检查之前，条件为
  `strong_buy_threshold > 0.0 and exp_map[s] < strong_buy_threshold` → `skips["strong_buy"] += 1; continue`。
- `skips` 字典由 `{"limit_up": 0, "min_edge": 0}` 扩展为含 `"strong_buy": 0`；写入 `skipped[d]` 的
  触发条件由 `if skips["limit_up"] or skips["min_edge"]` 补为 `... or skips["strong_buy"]`
  （末尾 `{k: v for k, v in skips.items() if v}` 自动过滤 0 计数）。
- 默认阈值 `0.0` 时新分支恒不触发，`strong_buy` 计数恒为 0，`skipped` 内容与改动前逐位一致。
- `scripts/run_backtest.py` 新增 CLI `--strong_buy_threshold`（default 0.0）透传给
  `run_backtest_target`；`metrics.json` target 段新增 `strong_buy_threshold` 与
  `n_skipped_strong_buy`（**只增不删**，保留 `min_edge`/`n_skipped_min_edge`/`n_skipped_limit_up`
  等全部旧键）；打印行、图题与 `NOTE_TARGET` 同步。
- 只改 target 模式：rolling 模式、`_simulate`、费用纯函数、`benchmark_index_nav`、`_close_holding`
  与 T 日决策 / T+1 open 买 / T+6 open 卖时序一律不动。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|---|---|---|---|
| 阈值语义 | 买入带内 `exp_ret >= strong_buy_threshold` 才买（绝对收益阈值） | 相对排名门槛；相对 min_edge 的边际门槛 | 用户确认「需较强上涨语义」= 绝对预测收益 |
| 默认值 / 关闭位 | `0.0` = 关闭；`< 0` raise | 0.01 默认；负值视为关闭 | 用户确认；默认零行为变化，保证向后兼容 |
| 作用范围 | 整个买入带 `rank <= target_size`（全部候选） | 仅后 `edge_tail_pct` 名 | 用户确认；与 `min_edge`（仅 tail）正交 |
| 与 min_edge 顺序 | **先 min_edge、后 strong_buy**；同一候选两者都命中 → 计 `min_edge`（先命中先计） | 先 strong_buy；二者合并计数 | 保留既有计数语义、默认零变化、结果确定 |
| 门槛位置 | `min_edge` 之后、OHLC 行查询 / 涨停检查之前 | 放在涨停检查之后 | 强买门槛是「预测层」过滤，先于可交易性检查 |
| 空槽处理 | 跳过候选、留现金、**不补位**（预算仍按 `nav_pre/target_size` 固定单槽） | 用更低 rank 候选补位 | 用户确认；保持单槽预算口径 |
| 缺预测（买入端） | 无需 None 分支：候选来自 `order_list`（即当日有预测的样本），`exp_map[s]` 恒存在 | 加 `exp_map.get(s) is None` 跳过分支 | 代码事实：买入候选 ⊂ `exp_map` keys |
| 缺预测（持仓端） | 沿用现状不变（`exit_on_nonpositive` 时缺预测不卖） | 改动退出逻辑 | 本次不动退出规则 |
| skip 计数 | 新增 `skips["strong_buy"]`（独立桶） | 复用 `min_edge` 桶 | 指标可分辨，便于调参归因 |
| metrics 字段 | 新增 `strong_buy_threshold` / `n_skipped_strong_buy` | 改名旧键 | schema 只增不删，兼容下游读 JSON |
| 参数校验 | 引擎 `strong_buy_threshold < 0` raise（唯一权威）；CLI 仅透传 | CLI 单独再校验 | 避免双份校验漂移 |

## Impact

| 模块 | 文件 | 操作 | 风险 |
|---|---|---|---|
| 回测引擎 | `backtest/engine.py` | modify | medium |
| 回测 CLI | `scripts/run_backtest.py` | modify | medium |
| 测试 | `tests/unit/backtest/test_engine.py`、`tests/unit/scripts/test_run_backtest_cli.py` | modify | medium |
| 文档 | `README_TRAINING_CHAIN.md`、`docs/per_code_normalization_spec.md`、`scripts/README.md` | modify | low |
| 进度 | `docs/agent/task/20260915_0005_add-strong-buy-gate/HARNESS_PROGRESS.md` | modify | low |

> 风险：改 `engine.py` target 买入路径若默认分支未完全短路会改变历史口径 → medium；
> CLI metrics 字段若删旧键会破坏下游读 JSON 工具 → medium；文档/进度为 low。
> **不波及** rolling 模式、`_simulate`、费用纯函数、`benchmark_index_nav`、`_close_holding`。

## Task Decomposition

### T01 引擎强买门槛 + skip 计数
- **文件**: `backtest/engine.py` (modify)；`tests/unit/backtest/test_engine.py` (modify)
- **描述**: `run_backtest_target` 增 `strong_buy_threshold: float = 0.0`；校验 `<0` raise；
  `skips` 增 `"strong_buy": 0`；买入循环在 `min_edge` 分支后新增
  `if strong_buy_threshold > 0.0 and exp_map[s] < strong_buy_threshold: skips["strong_buy"] += 1; continue`；
  `skipped[d]` 触发条件补 `or skips["strong_buy"]`；更新 docstring。
- **依赖**: 无
- **预估行数**: +45（code ≈15，测试 ≈30）
- **need_test**: 是
- **验收标准**: `strong_buy_threshold=-0.01` → `ValueError`；`strong_buy_threshold=0.05`、候选
  `exp_ret=[0.30, 0.03, 0.001]`、`target_size=3` → 仅 rank1 买入、nav 为「2/3 现金 + 1/3 买入」，
  `skipped[d] == {"strong_buy": 2}`；`strong_buy_threshold=0.0` 时 nav 与无此参数的既有断言逐位一致；
  与 `min_edge` 同命中时计 `min_edge`；与 `limit_up` 分支独立计数。
- **风险因子**: 默认分支必须完全短路（`> 0.0` 守卫），否则破坏历史口径；skip 桶归属顺序。

### T02 CLI 参数 / metrics / 打印
- **文件**: `scripts/run_backtest.py` (modify)；`tests/unit/scripts/test_run_backtest_cli.py` (modify)
- **描述**: `parse_args` 增 `--strong_buy_threshold`（type float, default 0.0）；
  `run_target_mode` 传给 `run_backtest_target`；metrics 增 `strong_buy_threshold`、
  `n_skipped_strong_buy`（聚合 `v.get("strong_buy", 0)`，保留旧键）；打印行、图题、
  `NOTE_TARGET` 与模块 docstring 示例同步。
- **依赖**: T01
- **预估行数**: +35
- **need_test**: 是
- **验收标准**: `parse_args(["--preds","x.npz","--mode","target"]).strong_buy_threshold == 0.0`；
  `--strong_buy_threshold 0.02` 解析为 0.02；target metrics 含新键且 `min_edge`/`n_skipped_min_edge`
  /`n_skipped_limit_up`/`target_size`/`sell_buffer` 等旧键仍存在；打印含 strong_buy 跳过计数。
- **风险因子**: metrics schema 兼容（只增不删）；CLI 默认值须与引擎默认一致 0.0。

### T03 回归 / 等价性测试 + 全量单测收尾
- **文件**: `tests/unit/backtest/test_engine.py`、`tests/unit/scripts/test_run_backtest_cli.py` (modify)
- **描述**: 显式回归断言「threshold=0.0 与未引入门槛时 nav/holdings/skipped 完全等价」；
  断言 rolling 模式路径未受影响；断言 metrics 旧键兼容；`unittest discover tests/unit` 全绿；
  touched 文件 `ruff check` 无错。
- **依赖**: T01, T02
- **预估行数**: +40
- **need_test**: 否（回归验证）
- **验收标准**: `uv run --project . python -m unittest discover tests/unit` 全绿；
  `uv run --project . python -m py_compile backtest/engine.py scripts/run_backtest.py` 通过；
  改动文件 `ruff check` 无新增报错；默认等价性断言通过。
- **风险因子**: 遗漏隐式依赖买入路径逐位结果的旧断言。

### T04 文档同步
- **文件**: `README_TRAINING_CHAIN.md` (§3.4)、`docs/per_code_normalization_spec.md` (§5.2)、
  `scripts/README.md` (run_backtest 选项表) (modify)
- **描述**: 三处补 `strong_buy_threshold` 说明：绝对预测收益阈值、默认 0.0=关闭、负数 raise、
  作用于整个买入带、不满足留现金不补位、与 `min_edge` 顺序（先 min_edge 后 strong_buy）。
- **依赖**: T01, T02
- **预估行数**: +15
- **need_test**: 否
- **验收标准**: 三处文档口径一致且与实现相符；`scripts/README.md` 选项表新增一行。
- **风险因子**: 文档与实现漂移。

### T05 交叉测试（3 阈值 × 2 退出规则 × 3 尺寸）
- **文件**: `docs/agent/task/20260915_0005_add-strong-buy-gate/HARNESS_PROGRESS.md` (modify)
- **描述**: 用现有 6 臂 preds（E0–E5）+ `logs/ohlc_full_2026-01-01_2026-08-31.npz`，对
  size ∈ {5,10,50} × 退出 ∈ {`--sell_buffer 500`, `--exit-on-nonpositive`} ×
  阈值 ∈ {0.0(基线), 0.01, 0.02, 0.03} 交叉运行 target 回测，产出 annual / excess_annual /
  `avg_cash_ratio` / `n_skipped_strong_buy` 汇总表落 HARNESS_PROGRESS。
- **依赖**: T01–T04
- **预估行数**: +30（无生产代码）
- **need_test**: 是（端到端）
- **验收标准**: 结果表落文件；阈值越大 `avg_cash_ratio` 与 `n_skipped_strong_buy` 单调不降；
  阈值 0.0 的结果与既有 `logs/backtest_idx_target_{b500,exitnp}_s{5,10,20}` 基线一致（同参数可复现）；
  结论显式标注「强买门槛」单变量影响。
- **风险因子**: 全市场 target 回测无并发、耗时；新数字不得与旧口径结果混用；需保证同 preds 同参数可复现。

## 风险与假设

### 风险
1. **默认等价性**：`strong_buy_threshold=0.0` 必须与改动前逐位一致，靠 `> 0.0` 守卫短路；T03 显式回归。
2. **skip 桶归属**：`min_edge`/`strong_buy`/`limit_up` 三者命中顺序须写死（min_edge → strong_buy → limit_up），
   否则计数不可复现；默认 min_edge=0.01 与阈值 0.01 在 tail 区存在重叠，需明确计 `min_edge`。
3. **metrics 兼容**：只增字段、不改名/删除；下游按旧键读取不受影响。
4. **缺预测语义**：买入候选来自当日 `order_list`，`exp_map[s]` 恒存在，无需 None 分支；
   持仓端缺预测行为不变（沿用「缺预测不卖」）。
5. **交叉测试资源**：全市场 target 回测无并发；`full_ohlc` 已存在，直接用现有 6 臂 preds。

### 显式假设
1. 阈值比较为 `>=`（等于阈值允许买入）。
2. `strong_buy_threshold` 仅作用于买入端；退出规则（`sell_buffer`/`exit_on_nonpositive`）不变。
3. 阈值只影响「是否买入」，不改变单槽预算 `(nav_pre/target_size)×capital` 与费用模型。
4. 阈值 0.0 是「关闭」哨兵，无法表达「exp_ret>=0 才买」的门槛（用户已确认可接受）。
5. 空槽现金不参与再分配（不补位）。
6. `weight` 字段仍记 `1/target_size`（信息字段），不因跳槽改变。
