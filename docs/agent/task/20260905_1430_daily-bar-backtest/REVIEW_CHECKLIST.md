# 审查清单 — daily-bar-backtest

> 生成时间：2026-09-05 14:30
> 需求：逐日（bar-by-bar）A股回测系统，模拟真实交易（T 收盘选股→T+1 开盘买入→持 5 日→T+6 开盘卖出，open-open 口径，跨 horizon=5 交易日），eval 现有模型（base-ep4/dual-ep7）在验证集 2025-07-01~2025-12-31 的实盘可执行效果；TopN=5/10/20，涨停跳过（×1.098，300/688 前缀 ×1.198），等权滚动 5 批并发，双边成本 0.15%，基准=全截面等权同口径，不处理 ST，卖出无跌停检查（第一版简化，报告注明）。

## 需求理解 — 显式假设

1. preds npz 的 dates 为标签日 T（窗口末日），即选股决策日；回测排序用 T 日 exp_ret。
2. 持仓收益必须用路径表 (T+1 open → T+6 open) 重算（open-open 口径，跨 horizon=5 交易日）；preds 的 true_ret（close[t+5]/close[t]-1）仅作参考，不得充当持仓收益。
3. 涨停 prev_close 取 T 日 close（用户确认口径）；code 前缀 300/688 适用 20% 档 ×1.198。
4. 每日新批投入 = 当前净值/5（动态等权）；到期回笼并入净值；5 批并发上限。
5. 交易日历由 parquet kline_time 唯一值派生；不引入外部日历依赖。
6. 尾部标签日不足 5 个后续交易日 → 路径 NaN，engine 剔除并计数。
7. test 集（2026+）当前无数据：ohlc 路径表与回测 CLI 均以参数化日期区间设计，未来零改动扩展。
8. 环境约束：后台两个全量训练运行中，T06 所有重跑步骤串行错峰；内存 15.9GB 禁止两个重数据任务并行。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| scripts | scripts/eval_bins_mapping.py | 修改 | L294-295 savez 处加 codes（数据集 index[0] 即 code，~5 行） |
| scripts | scripts/build_ohlc_path.py | 新增 | parquet→(code,label_date) 未来 5 日 OHLC 路径表 npz |
| backtest | backtest/__init__.py, backtest/engine.py | 新增 | 纯函数回测会计核心（涨停/成本/滚动/等权/净值） |
| scripts | scripts/run_backtest.py | 新增 | CLI 串联 preds+ohlc→报告（json/csv/png，基准超额） |
| tests | tests/unit/backtest/__init__.py, test_engine.py | 新增 | unittest 单测，合成数据确定性断言 |
| 运行 | logs/preds_*.npz（重跑）、logs/ohlc_path_val.npz、logs/backtest_*/ | 产物 | 全落 logs/（不入库） |

## 重复检测

| 搜索关键词 | 是否存在 | 位置/结论 |
|------------|---------|-----------|
| backtest/回测/净值/夏普/sharpe/max_drawdown/年化（全项目 *.py） | 否 | 仅 data/dataset.py:7 注释提及"回测"二字，无实现 |
| scripts/ 下回测脚本 | 否 | 仅 eval_bins_mapping.py / plot_topn_curve.py / recompute_bins.py |
| visualization/ 回测绘图 | 否 | 仅训练曲线 visualizer.py，与本任务无关 |
| 可复用：列裁剪读取模式 | 是 | data/dataset.py:147-169（T02 直接复制） |
| 可复用：绘图风格 | 是 | scripts/plot_topn_curve.py:19-25,110-111（Agg/YaHei/close/savefig） |
| 可复用：spearman/单测风格 | 是 | eval_bins_mapping.py:76 / tests/unit/data/test_data_dataset_triple.py |
| preds npz 现存缓存 | 是 | logs/preds_base_ep4.npz / preds_dual_ep7.npz（各 7.3MB，62 天，缺 code → T06 重跑） |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 静态检查 | `uv run ruff check .`（line-length 120）+ `python -m py_compile` 全部新增/修改文件 | HIGH |
| 2 | 单测 | `uv run python -m unittest tests.unit.backtest.test_engine -v` 全绿（≥10 用例） | HIGH |
| 3 | 会计正确性 | 涨停跳过、成本 0.15% 双边、5 批滚动到期、等权分配，合成数据手工可验证数值断言 | HIGH |
| 4 | 前视偏差 | T 日收益计算只依赖 ≤T+5 路径数据；篡改未来数据不影响 T 日净值（守卫用例） | HIGH |
| 5 | 口径一致 | 基准与策略同口径 (T+1 open→T+5 close)；禁用 preds true_ret 充当持仓收益 | HIGH |
| 6 | 数值精度 | 全链路 float64、日期 datetime64 归一（ns 单位一致）、argsort kind="stable" 可复现 | HIGH |
| 7 | 模块边界 | backtest/ 为纯函数库不 import torch/pandas 之外的重型依赖、不侵入 data/training；scripts 只做 CLI 薄壳 | MEDIUM |
| 8 | 绘图规范 | matplotlib 强制 Agg + Microsoft YaHei + unicode_minus=False + plt.close()，产物落 logs/ | MEDIUM |
| 9 | 性能/资源 | T02 列裁剪读 parquet（峰值<4GB）；T06 串行错峰（GPU 推理与后台训练不并行、重数据任务不并行） | MEDIUM |
| 10 | 导入合规 | 无通配符 import / 无未使用 import；异常不静默吞掉（路径缺失/形状不匹配显式报错） | MEDIUM |
| 11 | 兼容性 | eval npz 加 codes 键向后兼容；旧 preds npz（无 codes）被 run_backtest 读取时给出明确报错提示重跑 | MEDIUM |
| 12 | 文档一致性 | 报告输出注明简化假设（无卖出跌停检查、成本近似、无 ST 处理） | LOW |

## 环境与流程备注

- 非 git 仓库：本任务交付件不做 git commit，三件套直接落 task_dir（git 环节跳过）。
- 训练约束引用：AGENTS.md（train.py 唯一入口 / per_code 归一化 / logs 不入库）；MISTAKES.md 不存在；无 CLAUDE.md。
- 后台两个全量训练运行中：T06 的 4 个步骤必须逐个执行、间隔确认内存余量（总量 15.9GB，单数据任务峰值 5-8GB）。
