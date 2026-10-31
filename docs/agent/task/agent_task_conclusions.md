# 历史任务结论汇编

> 2026-10-31 精简：`docs/agent/task/` 下的过程记录（计划/进度/审查清单）已删除，只保留下列结论。
> 每条结论为事实与数字，过程流水账见 git 历史。当前口径以代码与 `docs/per_code_normalization_spec.md` 为准。

## 1. E0–E5 归一化六臂对照（20260913_2331）

- 训练口径：seed 42 / batch 1024 / lr 3e-4 / epochs 50 / patience 5；六臂均 epoch3 达最优、epoch8 早停；评估区间 2026-01-01~08-31（154 交易日，794,501 样本）。
- 截面 RankIC：E0 0.0248、E1 0.0302、E2 0.0415、E3 **0.0441**、E4 0.0339、E5 0.0399（全为正，E3 最高）。
- Top50 超额：E3 +9.95%、E1 +3.85%、E4 +3.68%、E2 +3.21%、E0 −1.51%、E5 −7.14%。
- Top100 超额：E3 +16.61%、E1 +9.53%、E4 +8.83%、E2 +8.50%、E5 +1.86%、E0 −0.22%。
- Top5 各臂全部跑输基准（小盘/换手噪声）；E5（G9 raw 入滚动）相对 E4 无增益。
- 设计决策：`close` 解禁入 P 组（相对化分母 `close[t-1]`）；18 个 G9 mask 合并为 1 个 shared `g9_observed_mask`（OR 18 列 finite，原 18 mask 有效秩≈1.05）；R 组 `asinh(x·scale)`，`amihud` `scale=1e12`；未见 code 回退 `global_stats`，禁止重 fit。
- 该「E3 信号最优」结论只停在 IC 层，未转化为可交易超额（见 §2、§4）。

## 2. 回测费用模型与 target 退出规则（20260914_2303）

- 费用：买佣 `max(买额×0.00025, 5)`；卖佣 `max(卖额×0.00025, 5)` + 印花税 `卖额×0.00025`；`capital` 默认 1,000,000（NAV 仍 1 起点，费用按 capital 折算）。
- target 单槽最低佣金阈值 `MIN_COMMISSION×(1+buy_rate)/buy_rate≈20005`，默认预算 10000 命中最低佣金分支；旧 `--cost_rate` 保留但 warning 后忽略。
- 基准由全市场等权改为沪深300（000300.SH）close-to-close，年化 −3.43%（旧等权 −12.66% 弃用）。
- 默认退出：`sell_buffer` 200→500；新增 `--exit-on-nonpositive`（`exp_ret≤exit_threshold`，默认 0.0），与 rank buffer 互斥。
- rolling top5/10/20 六臂全部跑输沪深300（最好为 E4 top10，超额 −7.13%，年化 −10.56%）。
- target size 5/10/20 方差极大、无一致正超额；`exit-on-nonpositive` 当时仅 E0 档稳定为正。
- 平均现金仓位 target 0.2%~12%（非大比例空仓）。commit `aa1e586`。

## 3. 强买门槛 `--strong_buy_threshold`（20260915_0005）

- 语义：target 买入带内候选 `exp_ret >= F` 才买，不满足者留现金、不补位；默认 `0.0` 关闭，`<0` raise；顺序 `min_edge → strong_buy → 涨停`。
- 24 组交叉（阈值 0/2%/3%/5% × b500/exitnp × size 5/10/50），现金比与跳过数随阈值单调不减。
- 2% 近乎无效：size 5/10 跳过≈0（模型头部预测已普遍 >2%），size 50 仅 ~110–480/臂。
- 3% 中等、5% 强：5% 时现金比 size50 44–67%、size10 21–45%、size5 14–33%；跳过数 size50 达 4,300–5,800/臂、size10 400–830/臂。
- 无一致正超额：改善例 E0 exitnp s5 t=5% +72.1%（基线 +22.5%）；恶化例 E2 exitnp s5 t=5% −52.3%（基线 −6.3%）。
- 收益差异由进入现金的比例驱动，不是选股 α；高阈值＝择时空仓，不能作为稳健 alpha 证据。commit `cb6abc1`。
- **口径警示**：以上全部数字出自旧引擎 `backtest/engine.py`（per-slot 预算 `nav/target_size`，跳过即留现金）。现行 `backtest/cnn_adapter/target_strategy.py` 的预算为 `可用现金/成交家数`，且另有 `_MAX_HOLDINGS=10` 独立持仓上限，被跳过槽位的现金会分摊给成交者。**两套口径的现金比不可直接比较**，当前 adapter 下同等阈值的现金比显著更低。复现旧结论须用旧引擎或显式实现 per-slot 预算模式。

## 4. 换手与行业归因（20260916_0010）

- 样本：33 个回测配置 × 6 臂，区间 2026-01-05~08-31（160 日），基准沪深300，行业用申万一级 point-in-time。
- 决定性结论：全部配置总 P&L **−11.77**；电子 +22.74；剔除电子后整体 **−34.5**（NAV 占比百分点）。
- E0 exitnp_s5（此前"最稳 +25.6%"）总 P&L +0.200，其中电子 +0.323（仅 4 笔、累计权重 0.8、平均 +40.4%）；其余行业合计为负。
- 出口规则是换手主导变量：exitnp 17.9×NAV vs b500 48.6×NAV（2.7 倍），平均持仓 21.6 日 vs 7.9 日。
- 成本拖累估算：b500≈7.3%/年、rolling≈7.0%/年、exitnp≈2.7%/年；成本差约 4.6pp，只占 17pp 超额差的约 1/4，其余来自持仓/择时路径。
- 强买门槛 t=2% 与 t=0 的换手/超额逐位一致，再次印证 2% 无效。
- 归一化模式（E0–E5）不改变行业暴露：同规则下臂间 `mean|active|` 差 <0.01；暴露主要随持仓数与门槛变化。
- 一致超配：电子、计算机、电力设备、医药生物、机械设备；一致低配：非银金融、通信、食品饮料、基础化工。
- 统计效力弱：小组合 + 单区间 160 日 + 单 seed，结论不能外推。

## 5. checkpoint NumPy 标量兼容（20261026）

- 根因：`CosineWarmup` 的 `np.cos` 使 optimizer `param_groups[0].lr` 与 scheduler `_last_lr` 成为 `numpy.float64`，`torch.load(weights_only=True)` 拒绝 pickle 里的 `numpy._core.multiarray.scalar`。
- 修复：保存前递归把 numpy scalar/dtype 转为原生 Python 标量；加载走 `weights_only=True` + `safe_globals` 最小 allowlist（NumPy scalar、`numpy.dtype`、`numpy.dtypes.Float64DType`）。
- `_codecs.encode` 不放行（去掉后仍可加载）；未知自定义类仍被 `weights_only` 拒绝，未引入 `weights_only=False` 回退。
- 运行范围：PyTorch ≥ 2.6（实测 2.12.0+cu130）、NumPy ≥ 2.4（实测 2.5.2）；NumPy 1.x 兼容分支不在支持范围。
- 验证：新/旧格式 checkpoint 均可加载，401 参数键 strict 载入且值不变，加载前后文件 SHA256 不变。commit `b747f56`。
