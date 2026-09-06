# 审查清单 — openopen-label-retrain

> 生成时间：2026-09-05 15:30
> 需求类型：feature（标签口径）+ 运行任务（三连串行重训）

## 需求理解

训练标签从 close-close（`close[t+5]/close[t]-1`）改为 open-open
（`future_ret_open[t] = open[t+1+horizon]/open[t+1]-1`，horizon=5 即 open[t+6]/open[t+1]-1），
使训练监督信号与 backtest/engine.py 实盘可实现口径（T+1 open 买 → T+6 open 卖）完全一致；
随后全串行重训三种 loss（base=EMD / dual=EMD+0.2×Huber / pure_reg=纯 Huber），
早停 patience 10→2（CLI 化）。52 类 BINS（linspace(-0.25,0.25,51)）、clip ±0.5、
模型/归一化/数据切分零改动。

### 显式假设（已由用户决策 20260905 锚定，无需再确认）

1. 新标签精确公式如上，t 为 code 有效行（is_trading=True 过滤后）内下标
2. 有效条件：open[t+1] 与 open[t+1+horizon] 非 NaN 且 open[t+1] > 0
3. 窗口边界随之收 1：max_s = n - seq_len - horizon（旧为 +1）
4. 三任务全串行（RAM 15.9GB + num_workers=0 本机强制）
5. 非 git 仓库，git 环节跳过（harness Phase 1.6/4 的 commit 步骤不适用）
6. data/AGENTS.md 无标签口径/Data Contract 段，本次无模块级 AGENTS.md 可同步项

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| data | data/dataset.py | 修改 | L111/259-289 标签段：纯函数抽取 + open 列提取 + max_s 收 1 + 注释同步；L147 read_cols 追加 "open" |
| tests | tests/unit/data/test_dataset_label_openopen.py | 新增 | 5 组 open-open 标签用例（TDD RED→GREEN） |
| tests | tests/unit/data/test_data_dataset_triple.py | 保留 | 现有 2 用例（三元组/clip）mock 注入，口径无关，回归保留 |
| train | train.py | 修改 | --patience CLI（+3 行）；L5 docstring 标签公式同步 |
| scripts | scripts/build_ohlc_path.py | 修改 | 仅 L6 注释："t+5 存在"→"t+1+horizon 存在"（新口径与该脚本尾部 NaN 语义反而更一致） |
| scripts | scripts/recompute_bins.py | 修改 | 仅 docstring 口径脱节警示（正文 future_ret_close/max_s+1 不动，BINS 不变决策不阻塞） |
| 运行 | logs/run_*/ ×3 | 新增 | 三连串行训练产物（运行任务，不进 quality gate） |
| 运行 | logs/preds_*.npz | 归档 | mv 至 logs/archive_closeclose/ 防口径混用 |

## 重复检测（全项目 grep future_ret / close-close 公式）

| 搜索目标 | 是否存在 | 位置 | 处置 |
|----------|---------|------|------|
| close-close 标签公式主实现 | 是 | data/dataset.py:267-272 | **T02 唯一改动点** |
| 内嵌公式副本 | 是 | scripts/recompute_bins.py:53 `future_ret_close()` + L88 `max_s+1` + L84 skip 条件 + L5/L10 注释 | 本次仅 docstring 警示；未来重算 bins 前必先同步（R4） |
| docstring/注释同步点 | 是 | dataset.py:111、train.py:5、build_ohlc_path.py:6、recompute_bins.py:5-10 | T02/T03 一并同步 |
| future_ret 消费方 | 是 | dataset.py:306/310/380（自产自销）、scripts/eval_bins_mapping.py:162-163、scripts/build_ohlc_path.py:6（注释） | eval 直读重建验证集的 groups["future_ret"] → **口径自动跟随，无需改代码**（推论已验证：eval 用同 dataset.py 重建 val 集） |
| 回测标签依赖 | 否 | backtest/engine.py 收益公式 open_t6/open_t1-1 独立于训练标签（ohlc npz 来自 build_ohlc_path） | 无需改，与新口径天然一致 |
| 现有同类单测 | 是 | tests/unit/data/test_data_dataset_triple.py（仅 mock 注入 groups，**标签公式本身零覆盖**） | 保留回归；新增 test_dataset_label_openopen.py 补公式覆盖 |
| PATIENCE 消费链 | 是 | train.py:84 config → trainer.py:86 config.get('PATIENCE',10) → early_stopping.py:20 | --patience CLI 链路闭合，键名大小写一致 |
| 可复用工具 | 是 | data/scaler.py:30 PerCodeGroupedScaler、criterion 三损失 | 零改动 |

### 三方对齐推论（写入风险基线）

- 训练标签（新口径）= eval 真值（eval_bins_mapping 直读 groups）= 回测持仓收益
  （engine.py open_t6/open_t1-1）→ eval/回测/训练三方自动对齐
- 唯一失配点：logs/preds_*.npz 旧缓存（close-close 真值）→ T04 归档

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 注释/docstring 公式同步（dataset.py:111/259、train.py:5、build_ohlc_path.py:6）；中文注释风格 | HIGH |
| 2 | 模块边界 | 仅 data 层标签语义变更，未侵入 models/training/criterion；eval/回测零改动 | HIGH |
| 3 | 数据安全 | 无硬编码凭证；标签仅依赖 open 列自身 | HIGH |
| 4 | 导入合规 | 纯函数新增于 dataset.py 模块级，无新 import（numpy 已有）；无通配符 | MEDIUM |
| 5 | 错误处理 | NaN/非正 open 防护显式（标 NaN 过滤，不静默吞异常） | MEDIUM |
| 6 | 性能风险 | 向量化实现（勿退化 Python 逐点循环 11M 行）；off-by-one（R8）；open-open 尾部更肥致边缘类占比激增（R3） | MEDIUM |
