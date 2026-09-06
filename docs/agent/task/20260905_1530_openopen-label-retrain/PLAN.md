# openopen-label-retrain Implementation Plan

> Generated: 2026-09-05 15:30
> Task Dir: docs/agent/task/20260905_1530_openopen-label-retrain/
> 需求类型: feature（标签口径变更）+ 运行任务（三连串行重训）

## Goal

训练标签口径从 close-close（`close[t+5]/close[t]-1`）改为 open-open
（`open[t+6]/open[t+1]-1`），与 backtest/engine.py 的实盘可实现口径
（T+1 open 买入 → T+6 open 卖出）对齐；随后全串行重训三种 loss
（base=EMD / dual=EMD+0.2×Huber / pure_reg=纯 Huber），早停 patience 10→2。
52 类 BINS、clip ±0.5、模型/归一化/数据切分零改动。

## 新标签公式（用户口径，禁止歧义）

```
future_ret_open[t] = open[t + 1 + horizon] / open[t + 1] - 1    (horizon=5)
有效条件: open[t+1] 与 open[t+1+horizon] 均非 NaN 且 open[t+1] > 0
t 为该 code 有效行（is_trading=True 过滤后）内下标
对齐性: 标签值 ≡ backtest/engine.py 持仓收益公式 open_t6/open_t1 - 1（engine.py:3-4,118）
```

## 窗口边界推导（新旧差异核算）

- 现实现 dataset.py:276：`max_s = n - seq_len - horizon + 1`，label_pos = s+seq_len-1
  最大取 `n-horizon-1`，需 close[t+horizon]=close[n-1] 存在（旧口径 t+horizon ≤ n-1）
- 新口径：需 open[t+1+horizon] 存在 → t+1+horizon ≤ n-1 → t ≤ n-2-horizon
  → `max_s = n - seq_len - horizon`（**每个 code 比旧口径少 1 个窗口**）
- 连带改动：`for t in range(n - cfg.horizon)` → `range(n - 1 - cfg.horizon)`（dataset.py:270）；
  预先 skip 条件 `n < cfg.seq_len + cfg.horizon` → `+ 1`（dataset.py:263，语义化，
  279 行 max_s<=0 兜底本可覆盖，行为等价但同步更清晰）
- 全市场 5166 股约少 5166 窗口（万分之一量级），无实质影响

## Architecture

单点改动集中在 `data/dataset.py` 标签构建段（259-289）：将 267-272 的向量化
future_ret 计算抽为模块级纯函数 `_future_ret_open_open(open_arr, horizon)`（可单测），
dataset 循环改调纯函数并传入 open 数组（open 列经 scaler.py:33 G1_Price 已在
feature_cols/read_cols 中，仍显式追加 read_cols 防御自定义 feature_cols 场景）。
valid_starts 的 NaN 过滤（283-289）口径自动跟随，无需改。eval/回测消费方读
groups["future_ret"] 自动对齐（见重复检测）。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| 标签公式实现 | 抽纯函数 `_future_ret_open_open` 模块级可单测 | 在 _load_and_prepare 循环内联改 | 公式目前无单测覆盖（现有 triple 测试仅 mock 注入 groups），纯函数使 UT1-UT4 无需构造 parquet |
| open 列获取 | read_cols 显式追加 "open" + group 提取 | 仅依赖 feature_cols 隐式包含 | open 虽经 G1_Price 入特征列，显式追加对自定义 feature_cols/use_factor_only 场景防御，零成本 |
| 有效条件 | open[t+1]>0 且两端点非 NaN | 沿用旧式仅 `!=0` | 用户口径明确 >0；open 理论恒正，<=0 视为脏数据标 NaN 过滤 |
| recompute_bins.py | 本次不改正文逻辑，仅 docstring 标注口径脱节警示 | 同步改 future_ret_close 为 open-open | 用户决策 BINS 不变，bins 重算不阻塞；其 `future_ret_close`(L53)/`max_s+1`(L88) 为 close-close 副本，改逻辑超本次范围，留待未来 quantile/11/13/15 类候选评估前必改（否则分位 bins 系统性偏移） |
| data/AGENTS.md | 不更新 | 同步 Data Contract 段 | 经查全文（4 条要点）无标签口径描述、无 Data Contract 段，无可同步项 |
| 旧 preds npz | T04 中 mv 至 logs/archive_closeclose/ 留档 | 直接覆盖重跑 eval | preds_base_ep4/preds_dual_ep7 的 true_ret 列为 close-close 口径，与重训后新口径不可混用；留档保留旧消融对照证据 |
| 三连训练顺序 | pure_reg → base → dual（建议） | 用户列举顺序 base→dual→pure_reg | pure_reg 预计 ~3 epoch 最快（~2.5h）先验证新标签链路无异常；dual 上轮最优且预计最长（~7h）放最后降低串行中断损失 |
| 早停 patience | CLI `--patience` 覆盖 config['PATIENCE'] | 直接改 config 默认值为 2 | 上轮消融 patience=10 的结论需可复现；CLI 参数保留旧口径复现能力，默认值仍 10 |

## Impact

| 模块 | 文件 | 操作 | 风险等级 |
|------|------|------|----------|
| data | data/dataset.py | modify（L111/259-289 标签段+docstring，L147 read_cols+open） | medium |
| tests | tests/unit/data/test_data_dataset_triple.py | modify（保留现有 2 用例） | low |
| tests | tests/unit/data/test_dataset_label_openopen.py | create（新增 5 组用例） | low |
| train | train.py | modify（L84 附近 +--patience CLI 3 行，L5 docstring 同步） | low |
| scripts | scripts/build_ohlc_path.py | modify（L6 注释"t+5 存在"→"t+1+horizon 存在"，口径一致性反而更好） | low |
| scripts | scripts/recompute_bins.py | modify（仅 docstring 脱节警示，不改逻辑） | low |
| docs | docs/loss_ablation_20260905.md | 不改（历史档，L18 口径为当时事实） | - |
| 训练产物 | logs/run_*/ （3 个新 run + best_model.pth） | create（运行任务产出） | - |

> data/dataset.py 变更触发 harness full 档（触发规则 #1 数据链路核心），
> test_scope=full：`uv run --project . python train.py --smoke --num_workers 0`。

## Task Decomposition

### T01: 单测先行（TDD RED）
- **文件**: tests/unit/data/test_dataset_label_openopen.py (create)
- **描述**: 针对 open-open 新口径先写失败测试（RED）：导入将新建的纯函数与旧实现行为断言。
- **依赖**: 无
- **预估行数**: +90
- **验收标准**: 全部用例在旧实现下 FAIL（RED 确认），且语法/导入路径正确
- **风险因子**: 测试构造需覆盖 NaN/非正值边界，勿用随机种子不稳定断言

### T02: dataset.py 标签 open-open（TDD GREEN）
- **文件**: data/dataset.py (modify), scripts/build_ohlc_path.py (modify 注释), scripts/recompute_bins.py (modify 仅 docstring)
- **描述**: 新增纯函数 `_future_ret_open_open(open_arr, horizon)`（向量化：有效掩码
  ~isnan 两端点 & open[t+1]>0，切片 open[horizon+1:]/open[1:n-horizon]-1）；
  _load_and_prepare 循环改为提取 `open = group["open"].values` 并调用纯函数；
  L263 skip 条件 +1、L270 循环上界 -1、L276 max_s 改 `n - seq_len - horizon`；
  L111/259-261 注释与 docstring 同步新公式；read_cols 追加 "open"。
- **依赖**: T01
- **预估行数**: +25 / -10
- **验收标准**: T01 全部用例 GREEN；`py_compile` 通过；ruff 通过
- **风险因子**: 向量化切片端点 off-by-one（open[1:n-horizon] 长度恰为 n-horizon-1）；
  勿动 valid_starts 逻辑（口径自动跟随）；勿动 __getitem__ clip ±0.5

### T03: train.py --patience CLI
- **文件**: train.py (modify)
- **描述**: `p.add_argument("--patience", type=int, default=config['PATIENCE'])` +
  `config['PATIENCE'] = args.patience`（main 覆盖段）；L5 docstring 标签公式同步。
  生效链路已验证：config['PATIENCE'] → trainer.py:86 `config.get('PATIENCE', 10)`
  → early_stopping.py:20。skip TDD（argparse 转发纯配置，早停行为由 trainer
  既有逻辑覆盖），用 `--help` + smoke 冒烟验证。
- **依赖**: 无（可与 T01/T02 并行）
- **预估行数**: +4 / -1
- **验收标准**: `--patience 2` 后日志/EarlyStopping counter 分母为 2（smoke 观察）
- **风险因子**: trainer 用 `config.get('PATIENCE', 10)`，键名大小写必须一致

### T04: 链路一致性验证 + 旧缓存处置（运行任务）
- **文件**: 无代码（备份 logs/preds_*.npz → logs/archive_closeclose/）
- **描述**: ① `uv run --project . python -m data.dataset --max_codes 10 --normalize per_code`
  观察标签分布 sanity（对比上轮 close-close 分布：边缘类占比、均值）；② 确认
  eval 三方对齐推论：eval_bins_mapping.py:162 直读重建验证集的
  groups["future_ret"] → 标签口径自动跟随 dataset.py，eval 无需改代码；
  回测收益公式独立于标签（engine.py open_t6/open_t1）亦无需改；③ 旧 preds npz
  归档防混用。
- **依赖**: T02, T03
- **预估行数**: 0（mv 2 个 npz 文件）
- **验收标准**: dataset 探查输出无 NaN 标签异常、分布形态合理；npz 已归档
- **风险因子**: 若 10 股小样本边缘类（<-25%/+25%）占比激增需扩到 --max_codes 100 复核

### T05: 三连串行训练启动与监控（运行任务，不进 quality gate）
- **文件**: logs/run_*/ 产物（create，运行产出）
- **描述**: 按"pure_reg → base → dual"串行执行（每条命令完成后再启动下一条，
  禁止并行——RAM 15.9GB + num_workers=0 本机强制）。启动前确认 GPU 空闲
  （nvidia-smi）。监控要点：EarlyStopping counter 分母=2、Val loss 封顶形态、
  run_log_dir 落盘。
- **依赖**: T04
- **预估行数**: 0
- **验收标准**: 3 个 run 目录各含 best_model.pth + config.json + training_curve.png

## 单测用例清单（T01 编写 / T02 转绿）

| # | 用例 | 断言 |
|---|------|------|
| UT1 | 公式正确性 | 构造已知 open 序列（含等差段），逐点断言 `fr[t] == open[t+6]/open[t+1]-1` |
| UT2 | 端点 NaN | open[t+1] 或 open[t+6] 为 NaN → fr[t] 为 NaN（停牌/缺数语义） |
| UT3 | 非正 open 防护 | open[t+1] <= 0（含 0 与负值）→ fr[t] 为 NaN；open[t+6]<=0 不除零（仅分子，正常计算除非 NaN） |
| UT4 | 尾部窗口截断 | n=seq+horizon+1 → max_s=1（恰 1 窗口）；n=seq+horizon → max_s=0（0 窗口，与旧口径差 1 的边界） |
| UT5 | 临时 parquet 集成 | tmp 目录写 2 code×80 天小表（含 is_trading=True 但 open=0 的脏行、尾部停牌 NaN），建 ParquetDataset 断言 valid_starts 过滤与具体标签值；另验证 __getitem__ y_ret clip ±0.5（现有 triple 2 用例保留回归） |

## 三连训练命令序列（串行，patience 2）

```bash
# 前置: nvidia-smi 确认 GPU 空闲
# 1) pure_reg（预计 ~3 epoch / ~2.5h，Val 上轮 ep1 即封顶 + counter 2）
uv run --project . python train.py --epochs 50 --batch_size 512 --num_workers 0 --patience 2 --pure_reg
# 2) base（预计 ~6 epoch / ~4.5h，Val 上轮 ep4 封顶）
uv run --project . python train.py --epochs 50 --batch_size 512 --num_workers 0 --patience 2
# 3) dual（预计 ~9 epoch / ~7h，Val 上轮 ep7 封顶，上轮最优配置）
uv run --project . python train.py --epochs 50 --batch_size 512 --num_workers 0 --patience 2 --dual_head --lambda_reg 0.2
```

- 预计总时长 ≈ 14h 训练 + 3×~20min 数据加载 ≈ 15h（串行过夜）
- 每 run 产物: logs/run_{ts}/（config.json / best_model.pth / training_curve.png / scaler_per_code.pkl）
- 完成后 eval 命令（口径已自动对齐，无需改 eval 代码）:
  `uv run --project . python scripts/eval_bins_mapping.py --ckpt logs/run_{ts}/best_model.pth ...`（按既有用法）

## 风险表

| # | 风险 | 等级 | 缓解 |
|---|------|------|------|
| R1 | 旧缓存口径混用：logs/preds_base_ep4.npz / preds_dual_ep7.npz 的 true_ret 为 close-close 口径，重跑 eval 会覆盖且与旧消融对照失真 | HIGH | T04 先 mv 至 logs/archive_closeclose/ 归档；重训后 eval 重新生成新口径 npz |
| R2 | 停牌 open NaN：is_trading=True 但 open 缺失/0 的脏数据行 | MEDIUM | UT2/UT3 端点 NaN 与 <=0 防护标 NaN → valid_starts 自动过滤 |
| R3 | 9 月妖股/隔夜跳空：open-open 含隔夜跳空，标签尾部比 close-close 更肥，52 类边缘类占比可能上升 | MEDIUM | clip ±0.5 挡极端；T04 标签分布 sanity 对比，边缘类 >1% 扩样复核并回报 |
| R4 | recompute_bins 口径脱节：其内嵌 future_ret_close/max_s+1 为 close-close 副本，未来 quantile bins/11/13/15 类候选评估若直接重跑会系统性偏移 | MEDIUM | 本次仅 docstring 警示（BINS 不变决策不阻塞）；未来重算前必先同步公式 |
| R5 | patience=2 对 dual 偏激进：上轮 dual ep7 封顶，若 ep8-9 出现 2 连升即早停，late convergence 被截断 | LOW | 用户已决策 patience 2；风险留档，若 dual 早停点 <ep7 封顶形态异常可人工评估续训 |
| R6 | 尾部窗口少 1 + val 尾部（12-31 后无数据）标签 NaN | LOW | 全市场 ~5166 窗口损失（万分之一）；val 尾部 NaN 自动过滤，与旧口径行为一致 |
| R7 | Windows 环境：num_workers>0 spawn OOM + 死锁；plt.show 阻塞 | LOW | 固定 num_workers 0、batch 512（上轮工程经验，visualizer 已 Agg） |
| R8 | 向量化切片 off-by-one（open[1:n-horizon] 端点） | MEDIUM | UT1/UT4 逐点+边界断言；py_compile + smoke 双保险 |
