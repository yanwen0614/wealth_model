# daily-bar-backtest Implementation Plan

> Generated: 2026-09-05 14:30
> Task Dir: docs/agent/task/20260905_1430_daily-bar-backtest

## Goal

建立逐日（bar-by-bar）A股回测系统：T 日收盘用模型 exp_ret 日截面排序取 TopN，T+1 开盘买入（涨停跳过），持有 5 日至 T+5 收盘卖出，评估 base-ep4 / dual-ep7 在验证集（2025-07-01~2025-12-31，62 交易日）上的实盘可执行效果，产出年化/夏普/最大回撤/胜率/月度表/逐日持仓/净值曲线（含全截面基准超额），并支持未来 test 集（2026+）零改动扩展。

## Architecture

新增顶层模块 `backtest/`（纯函数会计核心，numpy in/out，与 data/models/training/criterion 平级）+ 两个 CLI 脚本（`scripts/build_ohlc_path.py` 数据准备、`scripts/run_backtest.py` 报告串联）。数据流：eval 重跑产出含 code 的 preds npz → parquet 构建 (code,label_date)→未来 5 日 OHLC 路径表 npz → engine 按日滚动会计 → 报告产物落 `logs/`。会计正确性核心：**策略收益一律用路径表 (T+1 open → T+5 close) 重算，禁止直接用 preds npz 的 true_ret（close-to-close 口径）充当持仓收益**。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 持仓收益口径 | **open-open**：(T+6 open)/(T+1 open)-1，路径表重算，跨 horizon=5 个交易日 bar | 直接用 preds true_ret（close-to-close） | 用户指定 20260905；买卖均开盘时点，调仓节奏统一（T+6 open 卖出回笼资金恰可当日开盘买入新批） |
| 基准口径 | 全截面等权、同策略 open-open 口径（T+1 open→T+6 open），不筛涨停 | close-to-close 全截面均值 | 口径不一致会让超额混入口径差，无法归因选股能力 |
| 资金会计 | 每日新批投入 = 当前净值/5（动态等权），到期回笼并入净值 | 固定名义本金分 5 份 | 与净值序列自洽，几何复利，实现最简且无现金残留歧义 |
| 涨停判定 | T+1 open ≥ T 日 close×1.098；code 前缀 300/688 用×1.198；跳过并把资金等分给其余可成交票 | 跌停无法卖出模拟 | 用户确认规则；卖出跌停检查第一版不做（报告注明简化） |
| 交易日历 | 由 parquet kline_time 唯一值派生 | 引入外部日历库 | 无新依赖，与数据自洽 |
| 排序 tie-break | np.argsort(-exp_ret, kind="stable")，并列按截面出现序 | 随机打散 | 可复现（同 seed 同结果） |
| 尾部标签日 | 路径表不足 5 日标 NaN，engine 剔除并计数报告 | 截断持有期 | 与 dataset 标签生成口径一致（future_ret 要求 t+5 存在） |
| backtest 位置 | 项目根顶层包 `backtest/` | 塞进 scripts/ 或 training/ | 纯函数库需被 scripts 与 tests 双向导入；不侵入 data/training 边界 |

## Impact

| 模块 | 文件 | 操作 | 风险等级 |
|------|------|------|----------|
| scripts | scripts/eval_bins_mapping.py | modify（+5 行，npz 加 codes 键） | low（向后兼容：旧读取方按 z["exp_ret"] 索引不受影响） |
| scripts | scripts/build_ohlc_path.py | create | medium（3.43GB parquet 只读 5 列，注意内存错峰） |
| backtest | backtest/__init__.py, backtest/engine.py | create | high（新会计核心，数值/前视偏差风险） |
| scripts | scripts/run_backtest.py | create | medium（串联+报告，绘图遵循 Agg/close） |
| tests | tests/unit/backtest/__init__.py, tests/unit/backtest/test_engine.py | create | low（纯新增单测） |
| 运行 | logs/preds_*.npz 重跑、logs/ohlc_path_val.npz、logs/backtest_*/ 产物 | 运行任务 | medium（GPU/内存需与后台训练错峰串行） |

## Task Decomposition

### T01: eval 缓存补 code 列
- **文件**: scripts/eval_bins_mapping.py (modify)
- **描述**: 推理循环内已构建 `pairs = [ds.index[offset+i] ...]`（L163），`p[0]` 即 code。新增 `all_codes` 收集，`np.savez` 追加 `codes=np.concatenate(all_codes)`；--preds_cache help 同步注明含 code。
- **依赖**: 无
- **预估行数**: +5
- **验收标准**: `--max_codes 20 --preds_cache logs/tmp_preds.npz` 跑通后，`np.load(...).files` 含 `codes`，长度==exp_ret 长度，元素为 str；旧键 exp_ret/true_ret/dates 不变。
- **风险因子**: 无（向后兼容，旧 npz 读取方不读 codes 键）

### T02: OHLC 路径表构建脚本
- **文件**: scripts/build_ohlc_path.py (create)
- **描述**: 复制 dataset.py:147-169 读取模式：`pd.read_parquet(columns=["code","kline_time","open","close","is_trading"])`，过滤 is_trading、时间裁剪 [--val_start, --val_end + horizon+1 缓冲]、按 code 排序；对每 (code, 标签日 T) 输出 `t_close(T日close)、open_t1(T+1开盘)、open_t6(T+6开盘=卖出价；T+1..T+6 为该 code 后续 6 个交易日，不足标 NaN)`。npz 落盘 `--out logs/ohlc_path_val.npz`，键：codes(str)/dates(datetime64)/t_close/open_t1/open_t6(float64)。支持 --horizon(默认5，open-open 间隔=horizon 个交易日)。
- **依赖**: 无（与 T01 可并行）
- **预估行数**: +180
- **验收标准**: 62 交易日 × ~5109 code 路径表行数与 preds dates 截面吻合；抽查 3 只票手工核对 open_t1/open_t6 与 parquet 原值一致；尾部不足 6 日标签日为 NaN 且有计数输出；内存峰值 <4GB（列裁剪）。
- **风险因子**: 3.43GB parquet 全量读——必须列裁剪 + 与后台训练错峰（单进程峰值 5-8GB 禁令）

### T03: 回测会计核心（纯函数）
- **文件**: backtest/__init__.py, backtest/engine.py (create)
- **描述**: 输入输出全 numpy/float64。函数：`limit_up_mask(open_t1, t_close, codes)`（×1.098，前缀 300/688 ×1.198）；`run_backtest(exp_ret, codes, dates, path, topn, cost_rate=0.0015)` 按日滚动：截面排序取 TopN → 涨停过滤 → 可成交票等权（净值/5）→ T+1 open 买入 → **T+6 open 卖出（open-open 口径）** → 每批毛收益×(1-成本)；输出逐日净值 nav、逐批持仓记录结构化数组、被跳过计数；`nav_metrics(nav)` 年化/夏普(rf=0,日频√252)/最大回撤/胜率。禁止前视：T 日只用 ≤T 信息。
- **依赖**: T02（路径表 schema 约定）
- **预估行数**: +200
- **验收标准**: 合成数据下：涨停票被跳过且资金重分配正确；成本按双边 0.15% 精确扣减；5 批并发滚动到期不重叠不遗漏；open-open 收益计算（T+6 open/T+1 open）断言精确；截面为空/单票/全部涨停 3 类边界不崩且计数控。
- **风险因子**: 前视偏差（T 日信息不得进入 T 日前收益）；float32 精度——强制 float64

### T04: 回测 CLI 报告
- **文件**: scripts/run_backtest.py (create)
- **描述**: CLI 串联 `--preds`(多个 npz 多模型对比) + `--ohlc` + `--topn 5 10 20` + `--out_dir logs/backtest_<ts>`。输出：metrics.json（年化/夏普/回撤/胜率/月度表/基准超额，含"卖出无跌停检查"简化声明）、逐日持仓明细 csv、净值 png（matplotlib Agg + Microsoft YaHei + close，仿 plot_topn_curve.py:19-25,110-111）。
- **依赖**: T01（preds 含 codes）、T03（engine）
- **预估行数**: +180
- **验收标准**: 两个 preds npz 输入一次跑出双模型×3 档 TopN 对比表；基准（全截面同口径等权）与超额收益入表；产物齐全且全落 logs/ 下。
- **风险因子**:绘图未 close 导致内存泄漏；dates 时区/datetime64 单位不一致（ns vs us）需 np.datetime64 归一

### T05: engine 单测（TDD，与 T03 内环交替）
- **文件**: tests/unit/backtest/__init__.py, tests/unit/backtest/test_engine.py (create)
- **描述**: unittest 风格（仿 tests/unit/data/test_data_dataset_triple.py）。用例：涨停跳过（10%板/20%板各1）、成本精确扣减、滚动 5 批到期、等权分配、基准口径、边界（空截面/单票/全涨停）、前视守卫（篡改 T+1 后数据断言 T 日净值不变）。
- **依赖**: 无（先于 T03 编写，TDD 红绿循环）
- **预估行数**: +200
- **验收标准**: `uv run python -m unittest tests.unit.backtest.test_engine -v` 全绿，≥10 个用例，手工可验证的确定数值断言。
- **风险因子**: 合成数据须覆盖 300/688 前缀以测 20% 板

### T06: 重跑 eval + 首次真实回测（**用户指示暂缓 20260905**，状态 pending-blocked）
- **文件**: 无代码（运行任务）
- **描述**: 串行执行（后台两个全量训练运行中，GPU/内存错峰）：①eval 补 code 重跑双模型 ②`build_ohlc_path.py` ③`run_backtest.py` 双模型对比报告。每步间隔观察内存。**暂缓原因：用户指示系统建好+单测通过即可，真实数据运行延后。**
- **依赖**: T01, T02, T04, T05
- **状态**: 暂缓（不进入本轮执行）

## 接口约定（下游编码必须遵守）

- preds npz：`exp_ret/true_ret(float64)/dates(datetime64)/codes(str)`，逐样本对齐（顺序一致）
- ohlc npz：`codes(str)/dates(datetime64)/t_close/open_t1/open_t6(float64)`，行级对齐 (code,label_date)；open-open 口径卖出价 = T+6 open
- engine 签名：`run_backtest(exp_ret, codes, dates, ohlc, *, topn, cost_rate, horizon=5) -> BacktestResult(nav, holdings, skipped)`，纯函数无副作用
- 数值 float64、日期 datetime64、日期比较用 np.datetime64 归一后进行

## 增量需求（20260905 用户追加）：目标持仓模式（滞后带 + 费用感知过滤）

### T07: 全期日频 OHLC 矩阵（build_ohlc_path.py 扩展）
- **文件**: scripts/build_ohlc_path.py (modify +50)
- **描述**: 新增 `--full` 开关：输出全期日频矩阵 npz（键 `codes/dates/open_m/close_m`，shape [n_codes, n_dates] float64，行=code 列=交易日），供 target 模式任意跨度买卖价与涨停判定（prev_close=close_m 前列移位）。与现有 6 日窗口模式共存（默认仍窗口模式）。
- **依赖**: 无
- **预估行数**: +50
- **验收标准**: 矩阵行列与 codes/dates 对齐；抽查 3 票与 parquet 原值一致；NaN（停牌/未上市段）保留 NaN。

### T08: 目标持仓模式引擎（滞后带 + min_edge）
- **文件**: backtest/engine.py (modify +150)，新增纯函数 `run_backtest_target(exp_ret, codes, dates, full_ohlc, *, target_size=100, sell_buffer=200, min_edge=0.01, edge_tail_pct=0.3, cost_rate=0.0015) -> BacktestResult`
- **描述**: 事件驱动持有（无固定到期），每日截面：
  - 排名 rank=1 为分数最高；**买入带** rank ≤ target_size(100)；**卖出带** rank > target_size+sell_buffer(300)；(100,300] 区间持仓**继续持有不动**
  - T+1 open 执行：卖出（持仓且 rank>300 的票），买入（rank≤100 且未持有，经 min_edge 过滤）补空槽
  - **min_edge 过滤**：买入候选中 `rank/target_size > 1-edge_tail_pct（后 30%）且 exp_ret < min_edge(0.01)` 的单跳过，**空槽留现金**（不补位 rank>100）
  - 资金会计：等权目标持仓——每笔买入预算 = 当前 nav/target_size，股数=预算/(open×(1+cost))；nav = cash + Σ 股数×当日 open（前收盘口径逐日计价）；卖出回收=股数×open×(1-cost)
  - 数据尾部最后交易日强制按 open 平仓（计成本）
  - 排序 stable、float64、禁止前视（T+1 open 成交，T 日决策）
- **依赖**: T07（全期矩阵 schema）
- **预估行数**: +150
- **验收标准**: 合成数据：三态（≤100 补位买入 / 101~300 原样持有 / >300 卖出）；min_edge 双条件跳过且空槽现金；尾部强平；nav 逐日=现金+持仓市值；≥8 用例。

### T09: run_backtest.py 透传 target 模式
- **文件**: scripts/run_backtest.py (modify +40)
- **描述**: 新增 `--mode target`、`--target_size 100`、`--sell_buffer 200`、`--min_edge 0.01`、`--edge_tail_pct 0.3`；target 模式用 --full 矩阵 npz；报告并列 rolling/target 两模式指标。
- **依赖**: T08
- **预估行数**: +40
- **验收标准**: CLI 参数齐备（运行验证随 T06）。
