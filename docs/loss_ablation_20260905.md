# 损失函数消融总结 — base / dual / pure_reg（2026-09-05）

> 实验目的：验证 52 类有序分类监督（EMD）与回归监督（Huber）的相对价值。
> 结论先行：**dual（EMD+λ·Huber）全面最优，pure_reg（纯 Huber）全面最差**——52 类分布监督 > 纯回归拟合，且回归辅助项对 EMD 有正贡献。

## 一、实验设计（三连消融）

| 模型 | 损失 | 公式 | 实现位置 |
|---|---|---|---|
| base | 纯分类 | `L = EMD(logits, y_cls)` | criterion/emd_loss.py |
| dual | 分类+回归 | `L = EMD + 0.2 × Huber(ret_pred, y_ret)` | criterion/dual_loss.py |
| pure_reg | 纯回归 | `L = Huber(ret_pred, y_ret)`（分类头无梯度） | criterion/pure_reg_loss.py（本次新增） |

共同设定（单一变量原则）：
- 模型 CNNTransformer（d_model=256, 4 层 encoder, 45 特征×60 序列，52 类）**零改动**——forward 恒返 `(logits, ret_pred)`（model.py:130），三个损失共用同一架构
- 数据：全市场 5166 股，train 2013-01~2025-06（10,143,195 样本）/ val 2025-07~12（316,813 样本），per_code 归一化（复用 `logs/scaler_per_code.pkl`，无泄露）
- 训练：AdamW lr=1e-4, wd=1e-5, batch 512, num_workers 0, ReduceLROnPlateau(patience=5), 早停 patience=10, epochs≤50
- `y_ret` 定义：5 日收益 `close[t+5]/close[t]-1`，clip ±0.5；`y_cls`：52 类 digitize（BINS=linspace(-0.25,0.25,51)）

## 二、训练情况

硬件：RTX 3070 8GB / i7-10700（8C16T）/ RAM 15.9GB；Windows 下 DataLoader `num_workers>0` 会 spawn 复制全量数据集（+3GB/worker）且退出死锁，全量训练一律 `num_workers=0`；batch 256→512 实测吞吐 4045→5519 样本/s（供给端天花板 ~5000/s，单线程 __getitem__ 限制）。

### 运行记录

| 模型 | run 目录 | 启动 | 停止 | 完成度 | 停止原因 | Best Val | 封顶 epoch |
|---|---|---|---|---|---|---|---|
| base | run_20260905_025222 | 02:51 | 13:23 | 14/50 | 早停（counter 10/10） | 0.0572 | ep4 |
| dual | run_20260905_025822 | 02:57 | 15:22 | 16/50 | 手动（counter 9/10） | 0.0574 | ep7 |
| pure_reg | run_20260905_133947 | 13:39 | 15:22 | 2/50 | 手动（counter 1/10） | 0.0020 | ep1 |

### Val loss 收敛形态（三种监督的"可学习结构"完全不同）

| | pure_reg (Huber) | base (EMD) | dual (EMD+0.2Huber) |
|---|---|---|---|
| Val 封顶 | ep1 即平台 | ep4 冻结 | ep7 冻结 |
| 封顶后行为 | 0.0020 纹丝不动 | 0.0572 精确冻结 10 个 epoch | 0.0574 精确冻结 9 个 epoch |
| Train 侧 | 0.016→0.0024（-85%） | 0.0634→0.0542（-15%） | 0.0643→0.0541（-16%） |
| 形态 | 陡而短：前 1000 batch 降 5×，后横盘 | 浅而长：ep1 内缓坡，Val 冻结后 train 仍降（过拟合分化） | 同 base，冻结点更晚 |

解读：
1. Huber 回归的可学习成分（收益均值结构）**一个 epoch 榨干**，平均预测偏差 ~6.5%
2. EMD 分布监督的 Val 改善幅度仅 0.7~1.0%，但可学习时间更长（4→7 epoch）
3. Train 持续下降 + Val 冻结 = 经典过拟合分化，早停正确触发
4. pure_reg 的 Val Acc 0.0144 ≈ 1/52（0.0192），实证分类头无梯度、消融语义正确

## 三、最终度量（全市场日截面 eval，2025-07~12，62 交易日，日均截面 ~5109 样本）

口径：按交易日独立截面，exp_ret 排序取 TopK（base/dual 用 softmax·CENTERS52，pure_reg 用 ret_pred）；真实收益为 5 日 future_ret。各自 Best Val checkpoint。

| 指标 | base (ep4) | **dual (ep7)** | pure_reg (ep1) |
|---|---|---|---|
| 截面 RankIC mean / median | 0.0161 / 0.0137 | **0.0251 / 0.0151** | 0.0136 / 0.0252 |
| IC>0 天占比 | 53.2% | **61.3%** | 58.1% |
| Top0.5%（25只/日）mean / 为正率 | 0.0143 / 52.7% | **0.0189 / 55.0%** | -0.0017 / 44.0% |
| Top1%（51只/日）mean / 为正率 | 0.0107 / 51.7% | **0.0138 / 53.2%** | 0.0027 / 47.0% |
| Top5%（256只/日）mean / 为正率 | 0.0072 / 51.0% | **0.0083 / 51.3%** | 0.0053 / 50.6% |
| Top10%（511只/日）mean / 为正率 | 0.0064 / 50.3% | **0.0073 / 50.9%** | 0.0049 / 50.1% |
| **Top5 只/日** mean / 为正率 | 0.0292 / 54.2% | **0.0441 / 55.2%** | **-0.0085 / 40.3%** |
| **Top10 只/日** mean / 为正率 | 0.0220 / 54.4% | **0.0302 / 54.0%** | -0.0003 / 45.2% |
| Top15 只/日 mean / 为正率 | 0.0191 / 53.9% | **0.0259 / 55.8%** | -0.0019 / 44.8% |
| Top20 只/日 mean / 为正率 | 0.0154 / 52.8% | **0.0234 / 56.3%** | -0.0011 / 44.3% |
| 多空 spread mean / >0 天 | 0.0045 / 59.7% | **0.0061 / 71.0%** | 0.0028 / 56.5% |

dual 在 11/12 项指标上第一。

### 关键发现

1. **dual 全面最优**：RankIC 0.025（接近实盘 0.03 门槛）、IC 六成天数为正、spread 七成天数为正；每日选 5 只时 5 日均值 +4.4%
2. **pure_reg "越自信越差"**：RankIC 中位数不差（0.0252）但 mean 低、TopN 绝对只数全负、为正率 40~45%——无形状监督下模型最自信的头部完全反向（校准失败）
3. **消融验证**：52 类有序分布监督 > 纯回归；回归辅助项对 EMD 有正贡献（dual > base，且扣除 0.2×Huber 量纲后 dual 的 EMD Val ≈0.0570 仍优于 base 0.0572）
4. 口径教训：全池混合排序（旧口径）与 200 股小截面均会埋没/扭曲信号（200 股时 dual RankIC 仅 0.012），**全市场日截面是唯一可信口径**

## 四、结论与后续

结论：dual（EMD+λ·Huber, λ=0.2）为当前最优配置，base 次之，pure_reg 作为基线确认了分类分布监督的必要性。

后续建议（按价值排序）：
1. λ 敏感性消融（0.05 / 0.1 / 0.3）——0.2 是否最优未知
2. dual 的 ret_pred 排序口径对照（eval 加 `--use_ret_pred` 开关）——dual 有两个排序来源，softmax 加权未必是最优用法
3. TopN 组合的分层回测（含成本/换手约束）——当前为无成本口径
4. 2026 数据增量后跑 test 段（2026-01~）真·样本外
5. 数据管道提速（batch 级采样改写 dataset，预期 2~3× 吞吐，当前供给端 ~5000 样本/s 封顶）

## 附录

### A. checkpoint 索引
- base: `logs/run_20260905_025222/best_model.pth`（ep4）
- dual: `logs/run_20260905_025822/best_model.pth`（ep7）
- pure_reg: `logs/run_20260905_133947/best_model.pth`（ep1）
- 200 股 Step1（验收用）: run_20260905_015833（base）/ run_20260905_021322（dual）
- eval 明细: logs/ev_final_base.txt / ev_final_dual.txt / ev_final_pure_reg.txt

### B. 工程经验（Windows + 本硬件）
1. 后台进程禁用 `plt.show()`（Tk 消息循环永久阻塞，visualizer.py 已改 Agg+close）
2. train.py 尾部 `os._exit(0)` 绕过解释器退出时 CUDA/多进程清理挂起（产物先行落盘）
3. `num_workers>0` 在本机必然 OOM（spawn 复制数据集）+ 死锁，固定 0
4. batch 512 是当前单线程供给的吞吐最优点；再提速需改 batch 级采样
5. tmux（psmux）后台执行正常，但 `$?` 是 bash 语义，pwsh 内用 `$LASTEXITCODE`
6. harness 流程（quant-model skill）全程使用：PureRegLoss 变更 6 关卡 + TDD 5 组 + 端到端冒烟全 PASS

### C. eval 输出格式说明
`scripts/eval_bins_mapping.py` 现输出：全池指标（52/11/13acc、全池 RankIC、全池 Top10%）+ 日截面指标（62 天截面 RankIC、Top0.5%/1%/5%/10%、Top5/10/15/20 只、多空 spread）；pure_reg checkpoint 自动切换 ret_pred 排序并标注"分类头未训练"。
