# 进度跟踪 — daily-bar-backtest

> 生成时间：2026-09-05 14:30
> 需求：逐日 A 股回测系统，逐笔回测验证 base-ep4 / dual-ep7 在验证集（2025-07-01~2025-12-31）的实盘可执行效果
> 环境：后台两个全量训练运行中（GPU/CPU 高占用），T06 全部步骤串行错峰；内存 15.9GB；非 git 仓库（commit 跳过）

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | eval 缓存补 code 列 | completed | PASS（含于整体审查） | 向后兼容，旧读取方实测不受影响 |
| T02 | OHLC 路径表构建脚本 | completed | PASS（含于整体审查） | 仅代码交付，实际构建随 T06 暂缓 |
| T03 | 回测会计核心（纯函数） | completed | PASS（fix 1 轮） | open-open 口径实现正确 |
| T04 | 回测 CLI 报告 | completed | PASS（含于整体审查） | 仅代码交付 |
| T05 | engine 单测（TDD） | completed | PASS | RED 确认 → 17/17 全绿 |
| T06 | 重跑 eval + 首次真实回测 | **暂缓（用户指示 20260905）** | - | 系统验收后择机执行，见文末收口记录 |

## 最终收口（2026-09-05）

- **TDD**：17 用例（涨停 10%/20%、成本精确扣减、5 批滚动、等权分配、open-open 收益、基准同口径、前视守卫、空截面/单票/全涨停/NaN 边界、stable tie-break）；RED（ModuleNotFoundError）→ GREEN 中环 4 失败（3 处测试期望修正 + 1 处实现缺陷：空输入 nav 返回 [1.0]）→ 终态全绿
- **验证**：unittest 17/17 OK；ruff All checks passed；pyright backtest 0 errors（fix 后）；py_compile 全通过
- **fix 轮次**：1/2——issue #1（engine.py:134,178 float 包裹，pyright reportArgumentType）已修；issue #3（CHECKLIST L4/L9 旧口径措辞）已修
- **质量关卡**：会计正确性 PASS / 前视偏差 PASS / 边界 PASS / 兼容性 PASS / 规范 PASS / PLAN 接口一致性 PASS
- **留档改进项（LOW，不阻塞）**：
  1. engine.py:123-125 lut 查不到 (code,date) 静默 continue——建议 CLI 打印 lut 命中率防日期区间错位静默
  2. engine.py limit_up_mask 逐元素循环（32 万次毫秒级）可向量化；run_backtest 内联阈值未复用该函数
  3. REVIEW_CHECKLIST.md L48 残留一处旧口径子串（文档维护时一并修订）
  4. full 档冒烟（真实数据端到端）待 T06 解除后补验
- **git**：本目录非 git 仓库，Phase 1.6/4/5 的 commit/push 环节全部跳过

## 增量收口（20260905 下午）：目标持仓模式（滞后带 + min_edge）

- **T07**：build_ohlc_path.py +35 行（`--full` 全期日频 open_m/close_m 矩阵，NaN 保留）
- **T08**：engine.py 162→308 行（新增 `_close_holding` + `run_backtest_target(exp_ret, codes, dates, full_ohlc, *, target_size=100, sell_buffer=200, min_edge=0.01, edge_tail_pct=0.3, cost_rate=0.0015)`）——事件驱动持有：买入带 rank≤100 / 卖出带 rank>300 / (100,300] 不动；min_edge 双条件跳过空槽留现金；卖出先于买入回笼当日可用；nav 逐日 open 计价、停牌回退最近有效价；尾部强平；双边成本各计一次
- **T09**：run_backtest.py 127→202 行（`--mode target --target_size --sell_buffer --min_edge --edge_tail_pct --full_ohlc`）
- **TDD**：新增 10 用例（RED ImportError 确认 → GREEN 27/27 全绿）
- **Quality Gate**：PASS——6 关卡全过；all_issues：1 MEDIUM（#1 买入预算 nav_pre/target_size 无现金下限，持仓上涨时空槽预算可能超现金致 cash 变负=隐含融资，回测略偏乐观，PLAN 规格内行为，后续可加 `min(budget, cash)` 变体敏感性对照）+ 7 LOW（停牌卖出简化/NaN 回退无专项用例/docstring 补充/--full 忽略 --horizon 未提示/_HOLDINGS_DTYPE 字段名复用/双空行风格）
- **运行状态**：T06 仍暂缓（用户指示），真实数据端到端延后

## 执行详情

### T01: eval 缓存补 code 列
- **状态**：pending
- **依赖**：无
- **文件**：
  - `scripts/eval_bins_mapping.py` (modify)
- **预估行数**：+5
- **验收标准**：`--preds_cache` 产出的 npz 含 `codes`（str 数组，长度==exp_ret）；旧三键不变；旧读取方（plot_topn_curve.py）不受影响
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: OHLC 路径表构建脚本
- **状态**：pending
- **依赖**：无
- **文件**：
  - `scripts/build_ohlc_path.py` (create)
- **预估行数**：+180
- **验收标准**：`logs/ohlc_path_val.npz` 键 codes/dates/t_close/open_t1/open_t6；62 天 × ~5109 code；抽查 3 票与 parquet 原值一致；尾部不足 6 日标 NaN 有计数；内存峰值 <4GB
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: 回测会计核心（纯函数）
- **状态**：pending
- **依赖**：T02（路径表 schema 约定）
- **文件**：
  - `backtest/__init__.py` (create)
  - `backtest/engine.py` (create)
- **预估行数**：+200
- **验收标准**：limit_up_mask/run_backtest/nav_metrics 三函数纯 numpy；涨停跳过+资金重分配、成本双边 0.15% 精确扣减、5 批滚动到期、空截面/单票/全涨停边界不崩；全链路 float64；无前视（T 日只用 ≤T 信息）
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 回测 CLI 报告
- **状态**：pending
- **依赖**：T01, T03
- **文件**：
  - `scripts/run_backtest.py` (create)
- **预估行数**：+180
- **验收标准**：双 preds npz × TopN 5/10/20 对比表；基准超额入表；metrics.json + 逐日持仓 csv + 净值 png 齐全落 logs/backtest_<ts>/；绘图 Agg+YaHei+close；旧 npz 缺 codes 键时报错提示重跑
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T05: engine 单测（TDD）
- **状态**：pending
- **依赖**：无（测试先行，与 T03 红绿循环）
- **文件**：
  - `tests/unit/backtest/__init__.py` (create)
  - `tests/unit/backtest/test_engine.py` (create)
- **预估行数**：+200
- **验收标准**：`uv run python -m unittest tests.unit.backtest.test_engine -v` 全绿 ≥10 用例（含 10%/20% 涨停、成本、滚动、等权、基准、前视守卫、3 类边界）
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T06: 重跑 eval + 首次真实回测
- **状态**：pending
- **依赖**：T01, T02, T04, T05
- **文件**：无代码（运行任务，产物落 logs/）
- **预估行数**：0
- **验收标准**：base-ep4 vs dual-ep7 在 TopN=5/10/20 的年化/夏普/最大回撤/胜率/月度/超额对比报告落 logs/；62 交易日全覆盖；跑通无 OOM
- **Quality Gate 结果**：-
- **修复轮次**：0/2
- **执行顺序（串行，每步后观察内存）**：
  1. eval 重跑 dual_ep7（`--checkpoint logs/<dual run>/best_model.pth --max_codes -1 --preds_cache logs/preds_dual_ep7.npz`，~9min）
  2. eval 重跑 base_ep4（同法，~9min）
  3. `python scripts/build_ohlc_path.py --val_start 2025-07-01 --val_end 2025-12-31`（~数分钟）
  4. `python scripts/run_backtest.py --preds logs/preds_base_ep4.npz logs/preds_dual_ep7.npz --ohlc logs/ohlc_path_val.npz --topn 5 10 20`
