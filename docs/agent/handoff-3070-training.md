# Handoff: CNN 模型改进 — 3070 GPU 全量训练

> 生成时间: 2026-10-24
> 来源机器: GTX 970M (3GB VRAM, 已提交到 git)
> 目标机器: RTX 3070 (8GB VRAM, ~10-15x 更快)
> 同步方式: `git pull` → 训练 → 验证 → 迭代

---

## 一、起因 — 出了什么问题

### 核心问题
CNN-Transformer 模型在 **2026 年样本外测试中所有十分位均亏损**（D10 = **-19.3%**），模型完全失效。

### 四层根因

| 层 | 问题 | 说明 |
|----|------|------|
| 1 | **EMDLoss 只学排序不学绝对收益** | Earth Mover's Distance 是纯排序损失，52 个 bin 的相对概率分布正确 ≠ 绝对收益正确。模型可以在 RankIC=0.059 的同时所有分位绝对收益为负 |
| 2 | **没有空仓动作空间** | 回测永远选 top-N 买入，模型输出 52 类 logits → 永远选"最好的几只"→ 永远满仓。没有"今天不买"选项 |
| 3 | **训练集有 19.5% 下跌月但没学到离场** | 2015/2018/2022 有显著下跌，但模型没学会在这些时期空仓 |
| 4 | **2025→2026 市场结构断裂** | IC 与市场收益的符号关系翻转（正变负、负变正）。任何基于 2025 调参的后处理规则（IC 门、市场状态门）到 2026 全部失效 |

---

## 二、经过 — 什么方案试过、什么方案排除过

### 决策 1：默认启用 cs_rank + mkt_factors（已完成·已提交）
- **原因**：旧模型 IC 弱（0.0285）且月度不稳定
- **改动**：`config/defaults.py` CS_RANK=True, MKT_FACTORS=True, CosineWarmup, F=80
- **验证**：smoke 训练通过，F=53→F=80 确认生效

### 决策 2：新增三个诊断工具（已完成·已提交）
- `scripts/decile_diagnosis.py` — 十分位收益 + 驼峰检测（332 行, 16 单测）
- `scripts/signal_diagnostics.py` — RankIC 时序、Top-K 重合率、漂移、换手（1396 行, 44 单测）
- `training/sealed_eval.py` — 封存清单 + 指纹守卫（344 行, 30 单测）
- 验证：96 单测 PASS, ruff 零告警

### 决策 3：新增 RollingIcGate（已完成·可选启用）
- `backtest/cnn_adapter/order_strategy.py` 新增 RollingIcGate 类
- 基于滚动历史 IC 决定当天是否跳过交易
- **重要**：IC 门在 2025 有效但在 2026 几乎全部失效（市场结构断裂）
- 2026 的数据可能改变这个结论，暂时保留代码但不默认启用

### 决策 4：三种训练 hack 实验（已完成·全部失败）

| 方案 | 改动 | 2025 RankIC | IC>0 | 多空spread | 判决 |
|------|------|:----------:|:---:|:---------:|:----:|
| Baseline（无改动） | — | **0.0593** | 75.8% | 0.0096 | ✅ 最好 |
| ① 标签归零 | 崩盘日标签归 0 | 0.0323 | 62.5% | 0.0009 | ❌ 排序能力下降 |
| ② 双头交易门 | gate_head 分支预测是否交易 | -0.0401 | 40.0% | 0.0015 | ❌ 学反了 |
| ③ 自适应加权 | 下跌样本加重权重 | 0.0193 | 52.5% | 0.0002 | ❌ 几乎随机 |

**关键发现**：所有破坏排序信号的 hack 都降低 IC，**保留排序信号最重要**。

### 决策 5：推荐路线 C — Excess 标签口径（当前方向）
- **原因**：模型唯一可靠的能力就是截面排序（日内去均值前后 IC 不变）。Excess 标签把问题从"预测绝对收益"改为"预测跑赢大盘"，正好对齐模型真实能力
- 已有代码 0 行改动（`data/labels.py:110` `_cross_sectional_excess` + `data/dataset.py:254` `_apply_excess_labels`）
- **假设**：Excess 标签下 RankIC 应保持 ≈ baseline（EMD 损失在标签线性变换下保持排序）
- **风险**：如果 excess 标签也失效，退路是 `--label_mode absolute`（1 行改回）

---

## 三、结果 — 基线评估已完成

### 基线模型（absolute 标签，50 epoch，F=80）
- **模型文件**: `logs/relative/run_20261024_011940/best_model.pth`（已提交到 git）
- **训练配置**: 200 只股票, CS_RANK=True, MKT_FACTORS=True, CosineWarmup
- **全量验证**（5135 只股票, 2025-07-01 ~ 2025-12-31, 587,867 个窗口）:

| 指标 | 值 |
|------|-----|
| xs_RankIC_mean | **0.0400** |
| IC>0 占比 | **73.9%** |
| Top10% 均值收益 | **0.0149** |
| Top10% 正收益率 | **53.3%** |
| 多空 spread (Top10%-Bot10%) | **0.0030** |
| 预测缓存 | `/tmp/opencode/baseline_preds.npz` |
| 完整报告 | `/tmp/opencode/baseline_report.json` |

> **注意**: F=80（cs_rank+mkt_factors）的 baseline IC（0.04）低于旧 F=53 的 smoke baseline（0.0593）。可能原因：(1) 旧 smoke 只测 20 只股票，统计不稳定 (2) 多余特征引入了噪声。3070 上可以顺便跑一版 `--no-cs_rank --no-mkt_factors` 做消融对比。

### 当前 excess 训练状态（本机 GTX 970M，已终止）
- 500 只股票跑了 4/20 epoch
- Val loss 从 epoch 1 的 0.0432 持续上升到 epoch 4 的 0.0442 — **过拟合了**
- 结论：500 只股票数据不够，需要全量 5166 只才能收敛

---

## 四、3070 上做什么

### 环境

```bash
# 1. 同步代码
git pull

# 2. 装依赖
uv sync --offline  # 或 uv sync（在线）

# 3. 确认数据存在
ls -lh data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet

# 4. 确认 GPU
uv run --project . python -c "import torch; print(torch.cuda.get_device_name(0))"
# 应输出: NVIDIA GeForce RTX 3070
```

### Round 1：训练 excess 标签模型（全量 50 epoch）

```bash
tmux new-session -d -s cnn_excess_r1 \
  "uv run --project . python train.py \
    --label_mode excess \
    --epochs 50 \
    --batch_size 256 \
    --num_workers 4 \
    --seed 42 \
    > /tmp/opencode/train_excess_r1.txt 2>&1; \
   echo EXIT_CODE=\$? >> /tmp/opencode/train_excess_r1.txt"

# 每 60 分钟检查一次
sleep 3600 && cat /tmp/opencode/train_excess_r1.txt | grep -E "Epoch \[|Val Loss|Val Acc|Best Val" | grep -v "Batch"
```

**预期时间**：3070 上全量 50 epoch ≈ **4-6 小时**

### Round 1 验证

训练完成后，用刚提交的诊断工具：

```bash
# 1. 推理 2025 验证集
uv run --project . python -m scripts.eval_bins_mapping \
  --checkpoint logs/relative/run_*/best_model.pth \
  --parquet data/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet \
  --max_codes 0 \
  --horizon 10 \
  --batch_size 512 \
  --num_workers 0 \
  --seed 42 \
  --preds_cache /tmp/opencode/excess_preds_val.npz \
  --out /tmp/opencode/excess_report_val.json

# 2. 十分位诊断
uv run --project . python scripts/decile_diagnosis.py \
  /tmp/opencode/excess_preds_val.npz \
  --output_dir /tmp/opencode/excess_decile

# 3. 信号诊断
uv run --project . python scripts/signal_diagnostics.py \
  /tmp/opencode/excess_preds_val.npz \
  --output_dir /tmp/opencode/excess_signal
```

### 关键判断指标

| 指标 | 期望值 | 说明 |
|------|--------|------|
| xs_RankIC | ≥ **0.04** | 不低于 baseline，排序能力必须保持 |
| IC>0 占比 | ≥ **70%** | 与 baseline 持平 |
| Top10% 正收益率 | ≥ **0.014** | 不低于 baseline |
| 多空 spread | ≥ **0.003** | 不低于 baseline |
| **2026 回测 NAV** | **> 0** | 核心：不比 baseline 的 -19.3% 差就算进步 |

---

## 五、如果 Round 1 效果不理想 — 迭代方向

| 轮次 | 方向 | 改动命令 | 预期 |
|------|------|----------|------|
| **Round 2** | 回退 absolute 确认复现性 | `--label_mode absolute` | 应与 baseline 一致 |
| **Round 3** | EWMA 平滑 excess 标签 | 改 `data/labels.py:110` 加指数平滑 | 减少噪声 |
| **Round 4** | 去掉 cs_rank + mkt_factors | `--no-cs_rank --no-mkt_factors` | F=53，消融对比 |
| **Round 5** | 双头模型 | 恢复 `GATE_HEAD=True` | 需 50 epoch 让 gate head 收敛 |

**诊断失败根因的顺序**（如果结果不好）：
1. 先确认复现性（Round 2 → 是否 baseline 本身就有问题）
2. 再排查特征维度（Round 4 → F=80 是否真的比 F=53 好）
3. 最后才是损失/结构改进（Round 3/5）

---

## 六、参考资源

### 关键代码文件
| 文件 | 说明 |
|------|------|
| `data/labels.py:110` | `_cross_sectional_excess` 超额标签函数 |
| `data/dataset.py:254` | `_apply_excess_labels` 数据集调用 |
| `config/defaults.py:73` | `LABEL_MODE` 默认值 |
| `backtest/cnn_adapter/order_strategy.py` | RollingIcGate 类 |
| `scripts/decile_diagnosis.py` | 十分位收益诊断工具 |
| `scripts/signal_diagnostics.py` | 信号质量诊断工具 |
| `training/sealed_eval.py` | 封存清单验证工具 |

### 已提交到 git 的基线产物
- `logs/relative/run_20261024_011940/best_model.pth` — 50 epoch baseline
- `logs/relative/run_20261024_011940/config.json` — baseline 配置
- 本机 `/tmp/opencode/` 下还有预测缓存和报告，太大不入库

### 项目文档
- `AGENTS.md` — 架构、数据契约、命令大全
- `.opencode/memory/MEMORY.md` — 完整项目记忆
- `docs/per_code_normalization_spec.md` — 归一化规范

---

> **3070 上的关键约束**：不要在本机 `/tmp/` 外创建临时文件。每个 round 完成后把结果 commit 并 push，这样本机能同步看到进展。如果 5 轮都跑完还没解决，写新的 handoff 文档说明瓶颈在哪。
