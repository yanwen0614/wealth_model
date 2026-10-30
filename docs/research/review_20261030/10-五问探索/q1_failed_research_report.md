# Q1 失败研究路线梳理（只读探索报告）

**日期：2026-10-30**
**范围：本仓库及外置只读证据中所有"已尝试但失败 / 未达标 / 被放弃 / 未完成"的研究路线。**
**性质：只读盘点，不做新回测、不改源码、不重训练。所有数字均标注可查出处；找不到出处的写"未找到"。**

> 判定口径（本次联合目标）：① 扣成本后收益 ≥0；② 严格跑赢同期沪深 300；③ 实际持仓任一时点 ≤10 只。
> 三条必须同时成立。"未证明"≠"证明必亏"；本文严格区分**证伪**与**未完成**。

---

## 1. 路线一览表

| # | 路线 | 方法一句话 | 失败原因一句话 | 证据 | 状态 |
|---|---|---|---|---|---|
| 1 | 旧 CNN 52 类分类器 | 52 档 EMD 有序分类直接输出组合 | 预测塌缩到类 25/26，acc 9.75%，无排序力 | `research/goal/REPORT.md:5-11` | 彻底放弃 |
| 2 | CNN 主模型 A/B（target200 / rolling top10） | 主模型 + target/rolling 回测 | 2026 target 年化 -6.99%/-7.02%，rolling top10 更差 | `existing_oos_evidence_inventory_20261028/现有样本盘点.md:18` | 条件保留（仅基线） |
| 3 | λ 双头消融（target 5/10/20） | EMD+λ·Huber 五档 λ × 三种 target | λ/target 组合事后扫描，target20 违反 ≤10，且 λ 稍变结果由 +25% 跳到 -5% | `docs/lambda_ablation_20260906.md:47-56,69` | 彻底放弃 |
| 4 | 树 HGB/XGB 截面 rank（target20 / rolling） | GBDT 截面排序 + 动态退出 | 持仓 20 超上限；净值 1.002~1.015 属噪声；2026 rolling top10 -57%~-58% | `docs/prediction_target_and_tree_2026.md:62-81` | 条件保留（仅排序基线） |
| 5 | precision 精确优先规则包 | precision-coverage / 交集 / 输家否决 | VAL 有效（0.59→0.63/0.64），2026 全塌，不跨 regime | `research/precision/README.md:13-16`；`research/README.md:14` | 条件保留（待干净样本） |
| 6 | 市场方向择时门 | 18 市场特征 + fwd_up5 门控 | 2025 AUC 0.489/0.519≈随机；2026 与 2025 反向=噪声 | `docs/prediction_target_and_tree_2026.md:50-56` | 彻底放弃 |
| 7 | m_t 方向 / 幅度（12 方法） | 方向分类与幅度回归，expanding WF | 方向 AUC 0.50~0.55 且 CI 含 0.5；回归 OOS R² 全负 | `research/m_research/REPORT.md:27-53,89-100` | 彻底放弃 |
| 8 | alpha-m 双塔方向门 | α 塔 + m 塔参数完全分离，门控空仓 | 真实引擎年化 +51.43%→+9.25%，Sharpe 2.12→0.48 | `research/m_research/REPORT.md:157-171` | 彻底放弃 |
| 9 | m_t 波动缩放（vol targeting） | 仅用 abs(fwd5) 预测做仓位缩放 | 离线 Sharpe +0.088 但 CI 含 0；引擎版从未做 | `research/m_research/REPORT.md:173-191` | 条件保留（未验证） |
| 10 | regime 聚类门 | KMeans(m_ret, rv20) 二态 | riskoff 占比 70~90%，退化为常数 | `research/m_research/REPORT.md:63` | 彻底放弃 |
| 11 | goal 旧线（q5 / 可交易账户 / 个人版 Top20） | HGB 五分位 → T+1 open 账户链 | 纸面年化 46.76% 但账户口径仅 +5.54%；无停牌/退市/涨跌停处理；个人版 2026 -24.44% | `research/goal/REPORT.md:56-104`；`STRATEGY.md:33-35` | 条件保留（仅分散版参考）/ 旧数字过期 |
| 12 | goal_repro 高换手 rolling | 最新数据复现 rolling top10/top50 | 年化 -43.3% / -15.3%（top50 -0.9% / -15.9%） | `research/goal_repro/REPORT.md:19-28` | 彻底放弃（该形态） |
| 13 | 每日触发式调仓 | "崩了才动"的每日检查 + 阈值 | 触发率 96%+，笔数×10~12、费用×14~19，2026 -11.19% | `research/goal/STRATEGY.md:37-43` | 彻底放弃 |
| 14 | JKX 论文轨七路 | K 线成图 2D-CNN + 七种改法 | 三组全灭或边际，七路全灭，去 8 月后 2026 -28.9% | `docs/archive/paper_jkx_2024-2026_seven_routes.md:5-27` | 彻底放弃 |
| 15 | 冻结A 主链路（底仓 20） | 50% 门控 + 50% 裸奔，底仓 20 只 | 底仓 20 违反 ≤10；选项二预注册 REJECT；旧指数 +89.6% 为伪动 | `docs/archive/main_2015-2026_prereg_A.md:5-24`；`现有样本盘点.md:26` | 彻底放弃（本目标口径） |
| 16 | 散户单票胜率 ≥75% | ASL → pos_weight → 四路独立验证 | 天花板 52~58%，信噪比 0.1 对需求 0.67 | `docs/retail_winrate_research_summary_20260920.md:6,38-52,110-124` | 彻底放弃 |
| 17 | market_neutral 多空纸面 | topN-bottomN 等权、剥离 m_t | 引擎 long-only 无空头，只能纸面，不可交易 | `research/market_neutral/README.md:3-14` | 彻底放弃（本目标内） |
| 18 | 2021 八窗四策略（W1 侧） | B1/S1/S2/C70 机械回放 | W1 四策略在 300502 碎股处 fail-closed 中断，无 E 日 NAV | `eight_windows_second_audit_20261028/audit.md:7-25` | **待重做（未完成，非证伪）** |
| 19 | 2025 A/B 受限回放 | 5135 码信号宇宙做年度 A/B | 未知公司行动登记日 fail-closed，`NOT_EVALUABLE` | `validation_2025_ab_v2_abort_audit_20261029/REPORT.md:13-17` | **待重做（未完成，非证伪）** |
| 20 | W1 prefix / ceil 修复链（fix2/3/5） | floor/ceil 条件情景 + attestor + proof | mini PASS 但真实八分支/proof/绩效全 BLOCKED，三 pin 均 None | `w1_prefix_fix5_20261028/REPORT.md:19-25`；`w1_prefix_independent_qa_20261028/reverify4/REPORT.md:7-10` | **待重做（工程修复≠收益结论）** |
| 21 | W1 CA cutoff PIT 层（v3） | 只读 cutoff 合格性审计 + 未召回风险 | 4,812/4,812 哈希 PASS，但"cutoff 后事件 known_at 不足"，八分支未启动 | `w1_real_prefix_exploration_20261029_v3/FINAL_STATUS.md:1-7` | **待重做（未启动，非证伪）** |
| 22 | 2026-09 后干净前瞻考试 | 冻结信号 + 连续账本 + 同期基准 | 指数文件止于 2026-09-30，无事前冻结信号/执行链，判 NO-GO | `prospective_exam_feasibility_20261028/report.md:7-14`；`clean_exam_inventory.md:23` | **未完成（未启动）** |
| 23 | E0–E5 配置优选 / 强买门槛 / exitnp 规则包 | 33 目录×6 臂×6 规则做换手+行业 P&L 归因 | 全部配置总 P&L -11.77，电子 +22.74；剔除电子整体亏损 34.5 | `docs/agent/task/20260916_0010_turnover-industry-attribution/ATTRIBUTION_REPORT.md:1-14,92-100` | 彻底放弃（结论被归因推翻） |
| 24 | 损失消融 base/dual/pure_reg | 三种监督单变量对照（close-close 口径） | pure_reg 无效（Val Acc 0.0144≈1/52）；口径已作废且 λ 日志目录被覆盖 | `docs/loss_ablation_20260905.md:1-10,23-47`；`docs/lambda_ablation_20260906.md:23` | 彻底放弃（旧口径） |
| 25 | 全量训练计划（full_train_todo） | 200 股 3ep → 全量 base/dual 50ep | 算力不足（75h），只有 20 股 1ep 冒烟，自认噪声 | `docs/full_train_todo.md:1-12` | **未完成（未启动）** |
| 26 | 双头 / open-open 重训两个任务 | 计划改造 + 串行重训 | 任务未执行即被后续提交取代（superseded） | `docs/agent/task/20260905_dual-head/HARNESS_PROGRESS.md:4`；`...openopen-label-retrain/HARNESS_PROGRESS.md:4` | **未完成（被取代，无需重做）** |

**计数：共 26 条；彻底放弃 14 条（#1,3,6,7,8,10,12,13,14,15,16,17,23,24）；条件保留 5 条（#2,4,5,9,11）；待重做 4 条（#18-21）；未完成未启动/被取代 3 条（#22,25,26）。**

---

## 2. 逐条详细说明

### 2.1 旧 CNN 52 类分类器（输出塌缩）

**tried what**：沿用 `cnn` 早期 52 类离散标签 + EMD 有序分类，直接由 softmax 期望产出排序/组合。
**why failed**：验证集 8,408 窗口上模型塌缩到只预测类 25/26，总体准确率 **9.75%**，后半类加权精确率 **0.0028**。被判定为"极端类别不均衡 + 绝对收益阈值标签"导致的学习失败，而非单纯调参。retail 研究中路线①进一步印证：DL 基线 2026 top10 precision **42.8%** 低于基准正收益率 **45.9%**。
**evidence**：`research/goal/REPORT.md:5-11`（塌缩数字）；`docs/retail_winrate_research_summary_20260920.md:64-73`（42.8% vs 45.9%）。
**status**：彻底放弃（52 类直接分类的形态）。后续 EMD 分布监督仅作为损失对照保留。

### 2.2 CNN 主模型 A/B（target200 / rolling top10）

**tried what**：主链路 A/B 模型在 2025 验证、2026-01~08 测试，用 target(200/500/exit) 与 rolling top10 两种组合口径。
**why failed**：2026 target 年化 A **-6.99%**、B **-7.02%**（Sharpe -0.626/-0.514），超 HS300 **-5.12/-5.16pp**；rolling top10 年化 **-48.80%/-40.61%**。即"IC 存在但绝对收益为负"，且亏损来自模型不预测的市场项 m（2025 长仓收益 **70~82%** 来自 m）。
**evidence**：`existing_oos_evidence_inventory_20261028/现有样本盘点.md:18`；`docs/prediction_target_and_tree_2026.md:23,62-70`。
**status**：条件保留（仅作为排序基线与对照，不作达标候选）。注意 2026-01~08 属烧掉样本，这些数字不能用于新规则验收。

### 2.3 λ 双头消融（target 5/10/20）

**tried what**：固定 dual head（EMD + λ·Huber），扫描 λ∈{0.2,0.4,0.6,0.8,1.0}，再对每个 λ 扫 target∈{5,10,20}。
**why failed**：三重问题叠加。① 持仓超限：最优组合是 **λ=0.2 / target=20**（年化 25.4%、Sharpe 1.72、MDD 5.3%），20 只违反 ≤10。② 事后选择：λ 与 target 都是看过 2025-07~12 结果后挑的，非事前冻结。③ 结果不稳：λ 0.2→0.4 回测从 **+25.36%** 跳到 **-4.74%**，报告自己写"暗示当前评估可能存在噪声""最优可能带有随机种子偶然性"。此外报告未列同期指数，无法证明严格超大盘。
**evidence**：`docs/lambda_ablation_20260906.md:47-56`（target 矩阵）、`:69`（噪声自述）；`现有样本盘点.md:19`。
**status**：彻底放弃。

### 2.4 树 HGB / XGB 截面 rank（target20 / rolling top10）

**tried what**：16 维截面 rank 特征 + GBDT 排序，配 target 动态退出；另做 expanding 滚动 10 折。
**why failed**：四条硬伤。① **持仓超限**：既有动态退出组合目标 20 只。② **绝对值属噪声**：2026 target 净值仅 **1.002~1.015**、HGB 年化 +0.23%、XGB +2.25%，报告直接写"属噪声区，非可交易 alpha"。③ **rolling 更差**：2026 rolling top10 树 **-57%~-58%**，反比 A/B 的 -41%~-49% 更差。④ **事后筛选**：退出阈值与策略在研究后选优，且 2026 部分属烧样本。
**evidence**：`docs/prediction_target_and_tree_2026.md:62-81`（三个反证列在 :80）；`现有样本盘点.md:20-21`。
**status**：条件保留（"更优的截面排序基线"，可作集成/辅助过滤，不直接转产）。

### 2.5 precision 精确优先规则包

**tried what**：把目标从 IC 翻译成 `精确=P(true>0|选中)`，做 precision-coverage 曲线、A/B×HGB/XGB 交集（N=10/50/200）、输家否决（q=0.1/0.2）。
**why failed**：VAL 2025 上有效（precision **0.59→0.63~0.64**，容量 6~13%），但 **2026 全塌**，结论是"不跨 regime"。即规则只在被调参的那一年成立。
**evidence**：`research/precision/README.md:13-16`；`research/README.md:14`。
**status**：条件保留（已列入待干净样本验收队列，`research/README.md:25`），但不得在 2026 烧样本上再调。

### 2.6 市场方向择时门

**tried what**：等权收益指数 + 18 市场特征 + `fwd_up5` 标签，2013–2024 训练 / 2025 验证 / 2026 测试。
**why failed**：2025 验证 AUC logit **0.489** / hgb **0.519**（≈随机）；always-long 命中率 0.675 胜过多数量门。真实引擎 2025 裸奔 +42.54% → hgb 门控 +38.66%（只降 MDD）；2026 裸奔 -7.02% → hgb +0.59% / logit +6.86%，**两门跨年相反=噪声**。
**evidence**：`docs/prediction_target_and_tree_2026.md:50-56`。
**status**：彻底放弃（判定"不可行，仅弱风控"）。

### 2.7 m_t 方向 / 幅度预测（12 方法）

**tried what**：12 种方法（logit/ridge/lasso/EN/PLS/hgb/xgb_clf/LSTM/GRU/TCN/Transformer/三分类/分位/regime），EXT 37 维，expanding 年步进 walk-forward 2019–2025（7 折，purge=H），H=1/5/10/20。
**why failed**：① 方向：12 方法 AUC 全落 **0.50~0.55**，acc 全部低于 always-long；最优 TCN 0.5492 / xgb 0.5410 的 bootstrap 95%CI **含 0.5**（xgb 均值 0.5411，CI `[0.4968,0.5824]`），long-flat edge CI `[-0.00005,+0.00963]` 含 0。② 幅度：所有回归 OOS **R²<0**（ridge H5 -0.259、H10 -0.318）。③ 尾部/下跌：AUC 0.4976 / 0.5349，均在同一弱带。
**evidence**：`research/m_research/REPORT.md:27-53`（方法表）、`:89-93`（bootstrap）、`:97-100`（判定）。
**status**：彻底放弃（方向/幅度线已关闭；`research/README.md:13` 标"❄️关闭"）。

### 2.8 alpha-m 双塔方向门

**tried what**：α 塔（HGB-16，标签 close5d）+ m 塔（方向信号）**参数完全分离**，组合层零学习参数，m 塔 p>0.5 则空仓（滞后一日）。
**why failed**：真实引擎 2025 年化 **+51.43% → +9.25%**，Sharpe **2.123 → 0.480**，MDD 反而从 12.82% 升到 13.25%。离线 bootstrap 年化差 **-16.1pp，95%CI `[-29.2,-1.9]`，P(>0)=0.012 显著为负**。分年看门只在 2022/2024 弱市帮一点，2019/2021/2025 强市巨亏。
**evidence**：`research/m_research/REPORT.md:157-171`（§8.1）、`:188-189`（"方向门双塔：证伪"）。另一条同构证据：m_t 线最优门把 2025 年化 **+42.59% 打到 +7.23%**，仅换回 -0.14pp MDD（`m_research/REPORT.md:65-75`）。
**status**：彻底放弃。注意原始材料里 `+620%` 是**重叠口径假阳性**（任务明令禁止），已改非重叠，不得引用。

### 2.9 m_t 波动缩放（vol targeting）

**tried what**：用 \|fwd5\| 波动幅度预测做仓位缩放（α 收益 × clip(target/pred_vol,0,1)）。
**why failed**：信号本身显著（abs-return IC **+0.1787**、R² **+0.0366**，全场唯一 R²>0；bootstrap CI `[+0.1021,+0.2474]`）。但组合层：离线 Sharpe +0.088 而 **95%CI `[-0.124,+0.305]` 含 0，P(>0)=0.740 不显著**；MDD 从 -45.9% 改善到 -31.6%，年化从 +41.2% 降到 +37.5%。**引擎版从未做**（缩放需改引擎仓位接口）。
**evidence**：`research/m_research/REPORT.md:59,93,173-191`。
**status**：条件保留（仅风险控制假说，未引擎验证，须预注册 + 2026-09 后干净样本）。**禁止**将其 reinterpret 为方向信号。

### 2.10 regime 聚类门

**tried what**：KMeans(m_ret, rv20) 二态聚类做 regime 门（HMM 因缺 hmmlearn 未做）。
**why failed**：riskoff 占比 **70~90%**，标签退化为常数；off/on spread 虽存在但无门控价值。HMM 路线【未验证】。
**evidence**：`research/m_research/REPORT.md:63,128`。
**status**：彻底放弃。

### 2.11 goal 旧线（q5 五分位 / 可交易账户 / 个人版 Top20）

**tried what**：放弃 52 类分类，改截面五分位 q5 + 对 `future_ret_5d` 回归；再上 T+1 open 账户链（`account_engine_v2~v6`）、动态退出、Top20/Top50/Top100。
**why failed**：分三层递减。
- **纸面**：TEST Q5 年化 **46.76%**、Sharpe 1.4673、Q5−Q1 利差 **49.85%**，看起来达标；但基准自身年化 **+30.77%**，报告自认"Q5 的 46.76% 中约 **2/3 为 beta**"，且"无退市/停牌/涨跌停不可交易处理"。
- **可交易账户口径（50 万）**：同信号年化仅 **+5.54%**、Sharpe **0.2591**、费用 41,508.11 元（费损 **8.30%**）。落差主因：Top50 入选股隔夜跳空均值 **+118.5bps**（全市场仅 +7.5bps），alpha 集中在信号日→T+1 隔夜段，T+1 开盘交割系统性交出。
- **延长段 2026 熊市**：个人版（Top20 + 1 亿护栏）2026 单列 **-24.44%**，全程年化由 44.57% 稀释到 **20.28%**、回撤 **37.88%**，被明确"证伪、降级为备选"。
- 结构性硬伤：持仓数 Top20/Top50/Top100 全部远超 ≤10；无 ST/退市/长期停牌事前过滤（`STRATEGY.md:47` 自己列为"上实盘还缺什么"）。
**evidence**：`research/goal/REPORT.md:56-104`（§5.2/5.6/5.8）；`research/goal/STRATEGY.md:33-35,45-50`；`现有样本盘点.md:26`。
**status**：条件保留（仅"分散版"作方法参考）；**旧数字过期，不作现行策略绩效**。`research/goal` 已整体标 READ ONLY 冻结。

### 2.12 goal_repro 高换手 rolling 版本

**tried what**：用 cnn 现行栈（F53/H10/backtest-core/统一费率）+ F60 全集（70 列/1196 万有效行）重做 goal 三链；R2 账户回测本金 ¥2,000,000，对比 rolling top10 / top50 / target s100-buf500。
**why failed**：高换手形态直接亏穿：fold1 rolling top10 年化 **-43.3%**，fold2 **-15.3%**；top50 为 -0.9% / -15.9%。同报告给出根因："close 口径纸面 edge 经 T+1 open 执行后，高换手 rolling Bale 亏光"，与 goal `AUDIT §7` 同一教训。
**但需注意**：同报告的低换手 `target s100/buf500` 两折为 **+59.5%（Sharpe 1.72）/ +8.3%（Sharpe 0.39）**，R3 显示惯性 500 两折均胜 daily_hard(0)（+18.3%/-12.0%）。这部分**不是失败**，而是"低换手优于硬切"的正向方法线索；但 `s100` 目标数 100 只远超 ≤10，且本金 ¥2,000,000 与 W2 每策略 ¥1,000,000 口径不同，不可横向拼接。
**evidence**：`research/goal_repro/REPORT.md:11-36`。
**status**：彻底放弃（**仅指 rolling 高换手形态**）；`s100+惯性` 作为方法线索条件保留。

### 2.13 每日触发式调仓（"崩了才动"）

**tried what**：设想每日检查、只在排名崩坏时换仓的"便宜保险"，含 2026-09-05 补测的 Top100 三倍规则（买 Top100 / 跌出 300 卖 / 每日检查 + min-edge 0.01，v5 引擎亲跑）。
**why failed**：触发率 **96%+**，日排名噪声天天把持仓推出阈值；笔数 ×10~12，费用 ×14~19，持有期被打到 4~5 天。三倍规则 TEST 年化 45.58%（**−6.4pp** 于 calendar 挑战版）、24,114 笔、费损 **17.87%** + 滑点 **34.13%**、420 天全触发；2026 熊市年化 **−11.19%**（11,118 笔、持有 4 天）。机制总结："100 只持仓下每天必有股票掉出前 300，缓冲带形同虚设……纯属为噪音交税"。
**evidence**：`research/goal/STRATEGY.md:37-43`；`research/goal/README_ARCHIVE.md:26`（`opt_trigger` 判负，仅作负对照）。
**status**：彻底放弃。

### 2.14 JKX 论文轨七路（K 线成图 2D-CNN）

**tried what**：复现 Jiang-Kelly-Xiu 2023，K 线成图 v2 + 2D-CNN 二分类，A 股多头 target 回测（I5/I20/I60 × target100），再做七种抢救改法。
**why failed**：三组在 2026 全灭或边际：I5 -1.2%/-0.06（t20 +15.2% 唯一正）、I20 **-23.3%**/-1.39、I60 -5.6%/-0.28。死因分别写为"死于成本"（I5 2,139 笔摩擦 ~2.7% 吃掉 +0.95% 毛利）、"死于 beta"（I20 top 篮子 -1.12%）、"死于机制"（I60 acc 42.8% 方向做反）。七路验证**全灭或边际**：空仓门❌ / 对冲⚠️（A 股不可执行）/ 切换❌ / bottom 过滤恒等❌ / 降频净负❌ / 确信度加权 ±1pp⚠️ / 波缩❌。硬实锤："去 8 月后 2026 t100 为 **-28.9%**，全年靠 8 月单月续命"。另：IC 天花板≈主模型 B，成本高 10 倍（`docs/prediction_target_and_tree_2026.md:87`）。
**evidence**：`docs/archive/paper_jkx_2024-2026_seven_routes.md:5-27`。
**status**：彻底放弃（最终结论"多头 target 框架内 2026 无解……本系列关闭"）。

### 2.15 冻结A 主链路（底仓 20 只）

**tried what**：50% 门控户 + 50% 裸奔户（修复指数 MA40 门），底仓 20 只 + 动态退出 + TP30/TR12/MH90，资金静态 50/50。
**why failed**：① **底仓 20 只直接违反 ≤10 上限**；② 部分否决项：选项二（27 票卖出 + 回撤减半）S2 段 4.00 < 4.61，预注册 REJECT "永不再试"；全栈四层 2026 塌到 +2.9%；③ 旧指数（均值收盘价）2015-07-10 **+89.6% 伪动**不合格；④ 文档未给各段具体日期、HS300 同期收益、成本拆分、真实峰值/完整可复算账本。
**evidence**：`docs/archive/main_2015-2026_prereg_A.md:5-24`；`现有样本盘点.md:26`。
**status**：彻底放弃（本 ≤10 目标口径下）。作为"预注册纪律"的正面范例保留。

### 2.16 散户单票截面胜率 ≥75%

**tried what**：先修损失函数（ASL 负梯度失衡 → BCEWithLogitsLoss + pos_weight=2.0），再上四路独立验证（DL 基线 / GBDT 回归 / 市场择时过滤 / 二分类胜率 + 低波动）。
**why failed**：数学上不可达。5 日个股收益标准差 ≈6-8%、可预测 alpha ≈0.5-1%、**信噪比 ≈0.1**；要达 75% 方向准确率需信噪比 ≈0.67（IC≈0.35），当前最强模型 IC 仅 **0.075**，差 5 倍。四路 test 样本外天花板收敛在 **52-58%**（DL 42.8% / GBDT 54.7% / 择时 47.2%（oracle 55.3%）/ 分类器 52.0-53.9%）。
**evidence**：`docs/retail_winrate_research_summary_20260920.md:6,38-52,110-124`。
**status**：彻底放弃（"在本数据上不可达"）。

### 2.17 market_neutral 多空纸面验证

**tried what**：`exp_ret` 排序做 topN-bottomN 等权（N=10/100），用 `true_ret` 计价并剥离 m_t。
**why failed**：`run_backtest` 仅 long-only、`mode∈{rolling,target}`、**无 short 实现**，因此只能纸面，不得写成回测收益；且报告明示"不计费"。IC 恒等复核通过、LS 存在性成立，但"纸面≠可交易"。
**evidence**：`research/market_neutral/README.md:3-17`。
**status**：彻底放弃（在本目标 long-only ≤10 口径内）。

### 2.18 2021 W1 四策略（碎股中断）——**未完成，不是证伪**

**tried what**：W1 窗口（信号 2021-01-04~06-30，模型训练截至 2020-06-30、验证至 2020-12-31），四个**事先固定**策略 B1/S1/S2/C70，各 100 万元、五槽每槽 20 万元，次日开盘执行 + T+1 + 涨跌停/停牌/板别数量规则 + 成本。
**why failed（准确说：为何没有结果）**：四策略全部在 **2021-06-08** 处理 300502.SZ 送转时中断。前一日登记快照股数 B1 **4,000**、C70 **2,800**、S1/S2 各 **1,300**；乘公告原始每股转增 **0.4002532** 后分别为 1,601.0128 / 1,120.70896 / 520.32916，**都不是整数**，原始 runner 触发不可表示股数保护（`noninteger_or_unrepresentable_share_quantity`），fail-closed 停止。因此**没有 E 日 NAV、没有完整窗口收益、没有可核验的全窗持仓峰值**。
**关键点**：这是**实现能力边界 + 有效的 fail-closed 保护**，不是策略被证伪。W1 的失败也不构成"策略亏损证据"——片段成本（B1 佣金 6,816.43 / 印花 16,756.33 / 过户 681.64 / 滑点 95,046 元，182 笔成交）明确"不能推出窗口收益"。
**另一个未解事实**：官方公告（2021-030）规定"不足 1 股尾数按账户排序、同尾随机分配"，而**没有这四个模拟账户对应的全体账户排序和中登实际配发证据**，故真实获配数未知，不能假定 floor 或 ceil。
**evidence**：`eight_windows_second_audit_20261028/audit.md:7-25,62-71`；`three_day_strategy_report_20261029.md:74-82`；官方 PDF SHA `c09dfd553ff195857bef6a04a6b9ea57674865dd1e1b4b3fec666c4ee35277bd`。
**status**：**待重做**（需先取得真实碎股分配证据，或明确只报条件情景）。八窗整体 `actual_after_tax_target_eligible = 0/8`。

### 2.19 2025 A/B 受限年度回放——**未完成，不是证伪**

**tried what**：2025 年度 A/B 两账户回放，5135 码信号宇宙；2025 候选本地状态仅 174 码、行情 172 码，账户各自做 top5 资格筛选。
**why failed（准确说：为何没有结果）**：两账户均因**未知公司行动登记日**触发保护性中断。
- A：2025-08-22 遇 000601.SZ `dividend:17916`，登记录入未知 → 停止。中断时现金 **¥802,419.79268**，持有/锁定 000601.SZ 各 **33,600 股**（成本/标记价 ¥5.76），已记录成本 ¥3,376.20732，core 第 327 次更新。
- B：2025-06-06 遇 000506.SZ `dividend:63844`，同类守卫中断。持有/锁定 000506.SZ 各 **23,600 股**，已记录成本 ¥4,575.65435。
- 两者 `main_end_nav = null`、`buffer_end_nav = null`、`main_return_usable=false`、`target_verdict=NOT_EVALUABLE`。
**证据强度辨析**：A 的 000601 事件部分方案信息已找到（2025-08-05 半年报摘要公告 2025-066 明确"不派发现金红利，不送红股，不以公积金转增股本"，SHOULD be 可判定为"不分配"），**但官方全文页码/编号、id 17917 年度项目的股东大会决议原件与表决结果未闭合**，因此守卫是否误判无法定论；报告明确要求维持"中断/不可评估"，不得据局部账面外推。
**另一个非中断的硬伤**：该链本身数据覆盖不足——190 个 HDF 文件仅 174 码、40,796 状态行；268 个缺日 `cause_unknown`；raw 行情仅 172/174 码、44,116 行，000040.SZ / 000584.SZ **无 raw 与 adjusted 日线文件**；公司行动 359 条 dividend 中登记/除权/实施公告日各 229 空、派息日 231 空、红股上市日 355 空；`history_known_at = UNKNOWN`。
**evidence**：`validation_2025_ab_v2_abort_audit_20261029/REPORT.md:13-17`；`validation_2025_local_inputs_20261029/FINAL_REPORT.md:7-22`；`validation_2025_000601_official_20261029/FINDINGS.md`；`three_day_strategy_report_20261029.md:92-96`。
**status**：**待重做**（先闭合 CA 原件/事件链 + 补齐 174 码外宇宙与缺行情代码）。

### 2.20 W1 prefix / ceil 修复链（fix2 / fix3 / fix5）——**工程修复≠收益结论**

**tried what**：W1 中断后做 floor/ceil **条件情景**前缀研究：fix2 → fix3 → fix5，逐步加入 cutoff-only 八分支、独立进程 attestor、外置只读见证、12 路径 proof 门禁。
**why failed**：**工程门在 mini 范围通过，但在真实数据上从未跑通**。
- ceil 失败根因已定位：`CorporateActionContext._validate_positive` 同时要求**精确有理数乘积为整数**；ceil 情景把 `effective_ratio` 转成有限精度 Decimal 字符串，再由 `Fraction` 做精确有理数运算，S1/S2 残差 `4e-26`、C70 `1.2e-25`，故被拒。**不是 binary float 回乘误差**，且发生在 **2021-06-07 登记日 close observer hook**，不是 6/8 除权 hook。
- 真实八分支结果：v2 中 **5 条 exit 0 但 INCOMPLETE、3 条 exit 1 FAILED**（S1/S2/C70 的 ceil）。截止 6/7 的账本含 `execution_date=6/8` 的**待执行单**，不证明 6/8 成交。
- fix5：**94 项 mini 测试 + 46 项 core 测试 + Ruff/Pyright 全过**（独立 reverify4），但 `TRUSTED_PREFIX_ATTESTATOR_SHA256` / `TRUSTED_PREFIX_ATTESTATION_SHA256` / `TRUSTED_PREFIX_PROOF_SHA256` **三个 pin 均为 None**；真实八分支未启动、12 路径 proof BLOCKED、绩效 LOCKED。
- 更早一代独立 QA 甚至给出 **FAIL**（`w1_dual_core_identity_independent_qa_20261029/VERDICT.md:1-14`）：F4 attestor `:157` 清空 experiment、空身份攻击能输出 UNPINNED 见证；F5 查询 6/7 时底层加载 6/8；**审期发现外部改写源码/测试导致冻结完整性 FAIL**。
- 根本边界：即便工程全绿，**也无法代替中登实际碎股分配证据**，且 W1 版 8 个依赖接口（`staged_candidate_runner` 等）`git log --all` 0 命中，按当前 HEAD **不可原样运行**（`final_delivery_20261030.md:45,101`）。
**evidence**：`w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md:4-6,17-28`；`w1_real_prefix_independent_audit_20261029/REPORT.md:7-10,16-25`；`w1_prefix_fix5_20261028/REPORT.md:19-25`；`w1_prefix_independent_qa_20261028/reverify4/REPORT.md:7-10`；`w1_dual_core_identity_independent_qa_20261029/VERDICT.md`。
**status**：**待重做**（须补齐 8 个 W1 版接口 + 重设与当前文件一致的 pin + 取得真实获配证据；否则只报条件情景与中断）。

### 2.21 W1 CA cutoff PIT 层（v3）——**未启动，不是证伪**

**tried what**：为 cutoff-safe 前缀重跑做 PIT 合格性审计：对 `dividend_range_rows.json` 全量 8,740 行做只读扫描，区分"物理读取 / descriptor 枚举 / 业务影响"三层，设计 observed / eligible / unknown 分层快照。
**why failed**：**前置门就未通过，八分支未启动**。v12 artifacts 哈希 4,812/4,812 全 PASS（这本身是成功的机械检查），但结论是"cutoff 后事件 descriptor 的 `known_at` 证据不足"，保持 fail-closed，`outputs/` 不存在，未生成账本、proof 或 attestation。统计层面：公告日期 ≤cutoff 2,497 条；登记日 ≤cutoff 1,306 条；**未来 ex 日 2,279 条中 1,959 条公告日期晚于 cutoff**；现有证据"不能断言这 1,959 条已改变 W1 截至 cutoff 的账本"，但"完整 descriptor 加载、日期集合、源历史版本未知也不构成 PIT 隔离证明"。
**性质澄清**：这是**主动停止**（判断证据不足），不是发现策略无效。它的价值是排除了"按未来 ex 日期剪裁事件"这一错误做法——300502 正是反例：公告在 cutoff 前、未来 ex 不能因日期在未来而删掉。
**evidence**：`w1_ca_cutoff_availability_20261029/ANALYSIS.md:5-20`；`w1_real_prefix_exploration_20261029_v3/FINAL_STATUS.md:1-7`。
**status**：**待重做**（需独立公开证据锚定 `known_at`，含公告时刻时区/时分；无时刻按保守边界处理）。

### 2.22 2026-09 后干净前瞻考试——**未完成（未启动）**

**tried what**：计划在 2026-09 之后的新数据上，用事前冻结模型信号 + 连续执行账本 + 完整同期基准做唯一合法验收。
**why failed（准确说：为何无法开始）**：① 沪深 300 指数文件精确止于 **2026-09-30**，2026-10-01 后 0 行，**没有可用的同期基准**；② 不存在事前冻结的 2026-09 后模型信号（W1/W2 权重训练止于 2021，信号 2026-10 事后生成）；③ 未发现已运行的每日盘前冻结信号 / 真实订单成交 / 连续账户快照链；④ 业务日期 ≠ 盘前可得时间，mtime 不能作 PIT 证书。评估裁定 **NO-GO**。
**evidence**：`prospective_exam_feasibility_20261028/report.md:7-14`；`clean_exam_data_inventory_20261028/clean_exam_inventory.md:23,33`。
**status**：**未完成（未启动）**。这不是"策略失败"证据，是"考试还没开考"。

### 2.23 归一化 E0–E5 配置优选 + 强买门槛 / exitnp 规则包——**被归因证伪**

**tried what**：在 2026-01-05~08-31（160 交易日）上跑 33 个回测目录 × 6 臂（E0–E5）× 6 种规则（rolling topn5/10/20、target b500、target exitnp、强买门槛 sbg 三档），做换手 + 申万一级行业暴露 + 行业 P&L 归因，判定"哪个配置最好"。
**why failed**：**决定性发现——所有配置的收益来源是电子行业的一次行情，不是选股 α**。全部配置总 P&L = **-11.77**（NAV 占比单位），其中 `801080 电子` = **+22.74**，电子占比标为 **-193%**，即**剔除电子后所有配置整体亏损 34.5**。此前"最稳 +25.6%"的 E0 exitnp_s5，总 P&L 仅 +0.200，其中电子 **+0.323**——电子单行业已超过全部盈利，其余行业合计为负；而电子只有 **4 笔交易**、累计权重 0.8、平均 +40.4%、胜率 100%（4 笔全胜＝典型小样本运气）。
次要失败点：① **强买门槛 t=2% 完全无效**——`sbg_*_t0.00` 与 `t0.02` 的换手/超额**逐位一致**，因为"模型头部预测已普遍 >2%"；t=5% 虽把换手压到 12.9–25.3×NAV，但现金比升到 30–61%、行业集中度反而抬高。② **归一化模式 E0–E5 对行业暴露几乎无影响**（臂间 `mean|active|` 差 <0.01），因此此前"E0 无状态更稳健"的解释缺乏证据。
附带的正向线索（非失败）：**出口规则是换手第一驱动**——exitnp 17.9×NAV vs b500 48.6×NAV（2.7 倍），持仓期 21.6 天 vs 7.9 天；成本差约 4.6pp/年，但 17pp 的超额差中成本只占约 1/4。且 exitnp 超额随 size 单调改善（s5 -14.3% → s50 +11.5%），这正好与大组合分散一致，但也与"≤10 只"目标相反方向。
**evidence**：`docs/agent/task/20260916_0010_turnover-industry-attribution/ATTRIBUTION_REPORT.md:1-14,26-36,90-100`；`HARNESS_PROGRESS.md:"关键结论"` 第 1–5 条。
**status**：彻底放弃（"E0/某配置最优"的结论本身被推翻；该 160 日区间与 2026-01~08 属烧样本）。归因方法（换手/行业/P&L 分解）值得保留复用。

### 2.24 损失函数消融 base / dual / pure_reg（close-close 时代）

**tried what**：单变量对照三种监督：纯 EMD 分类（base）、EMD+0.2·Huber（dual）、纯 Huber 回归（pure_reg），同架构同数据（train 2013-01~2025-06 / val 2025-07~12，per_code 归一化）。
**why failed**：pure_reg **全面最差**且实际上是"无效实验"——val loss ep1 起完全平台（0.0020 纹丝不动）、Val Acc **0.0144 ≈ 1/52（0.0192）**，实证分类头无梯度；Top0.5% 收益 **-0.0017**、为正率 **44.0%**（低于随机 50%）。且三种监督的 val loss 在 ep4~ep7 后"精确冻结 9~10 个 epoch"，train 仍降，属经典过拟合分化。
**必须标注的口径陷阱**：该报告自身声明"训练标签和真实收益仍为 **close-close** 口径，结果数字原样保留，仅用于历史追溯。**不得与当前 parquet 的 open-open 标签、checkpoint 或回测结果混用**"。因此 base/dual 的 RankIC 0.0161/0.0251 也是**旧口径**，不可与现行 F53/H10 open-open 的 0.05~0.08 直接比较。
此外：λ=1.0 与 0.8 曾**共用同一日志目录导致 best_model.pth 覆盖**（`lambda_ablation_20260906.md:23` 自述），即早期 λ 消融存在产物污染。
**evidence**：`docs/loss_ablation_20260905.md:1-10,23-47`；`docs/lambda_ablation_20260906.md:23`。
**status**：彻底放弃（close-close 口径整体作废）；结论"dual 优于 base 优于 pure_reg"仅作方法学参考。

### 2.25 全量训练计划（full_train_todo）

**tried what**：计划双头 52+1 落地后跑 200 股 3 epoch 验证 → 全量 baseline → 全量 dual（50 epoch），用于判定 base vs dual。
**why failed（准确说：为何未执行）**：算力不足——"970M 3GB 估算 **80~97 min/epoch**，全量 50 epoch 约 **75h**，too 重，换卡后跑"。已有的只是 **20 股 1 epoch 冒烟**：baseline Val 0.0542/11.77% vs dual Val 0.0549/10.73%，RankIC **+0.13 vs -0.09**，报告自认"1epoch 噪声"。**因此"dual 优于 base"从未在全量上验证过**。
**evidence**：`docs/full_train_todo.md:1-12`。
**status**：未完成（未启动）。注意：`docs/agent/task/20260905_dual-head` 与 `20260905_1530_openopen-label-retrain` 两个任务目录被标为 `superseded`（"本任务未执行即被后续工作取代"），属同类"未完成而非证伪"。

### 2.26 双头任务 / open-open 重训任务（工程任务被取代）

**tried what**：2026-09-05 两个计划任务：① `20260905_dual-head`（EMD+0.2Huber 双头 52+1 改造 + 冒烟对比）；② `20260905_1530_openopen-label-retrain`（标签 close-close→open-open，三 loss 串行重训）。
**why failed（准确说：为何未执行）**：两个任务均在 2026-09-12 被标 `superseded`——"本任务未执行即被后续工作取代"，全表 pending → superseded，不再恢复。原因不是失败，而是**后续提交已直接实现**（`train.py` 已有 `--dual_head/--pure_reg/--lambda_reg`；标签已是 `future_ret=open[t+6]/open[t+1]-1`）。
**evidence**：`docs/agent/task/20260905_dual-head/HARNESS_PROGRESS.md:4`；`docs/agent/task/20260905_1530_openopen-label-retrain/HARNESS_PROGRESS.md:4`。
**status**：未完成（被取代，无需重做）。


---

## 3. 失败模式归纳

把 26 条路线并排看，失败集中在这七个模式上，且它们**相互耦合**——这也是为什么单点修一个模式不足以救活策略。

### 3.1 失败模式清单

| 模式 | 命中路线 | 具体表现（关键证据） |
|---|---|---|
| **M1 事后选择 / 参数扫描** | #3 λ 与 target、#4 树退出阈值、#5 precision 阈值、#11 goal 个人版、#15 冻结A、#23 E0–E5 | λ 0.2→0.4 从 +25.36% 跳到 -4.74%（`lambda_ablation:47-49`）；E0 最优其实来自电子 4 笔（`ATTRIBUTION_REPORT:92`）；报告自认"结果现已可见，不得事后只挑 B1" |
| **M2 持仓数违反 ≤10 上限** | #3 target20、#4 target20、#11 Top20/50/100、#12 s100、#14 target20/100、#15 底仓20、#23 exitnp s20/s50 最优 | 这是**最高频的硬门槛违反**：几乎每个"收益较高"的候选都建立在 20~100 只仓位上；而归因显示"持仓越多超额越好"（exitnp s5 -14.3%→s50 +11.5%，`ATTRIBUTION_REPORT`§2），与 ≤10 目标**方向相反** |
| **M3 样本已观察 / 烧样本** | #2,3,4,5,7,8,11,12,14,16,23 | 2026-01~08 为项目红线烧样本；W1/W2 信号是 2026-10 事后生成（`clean_exam_inventory:10-20`）；λ/target/阈值全在已看过的 2025H2 上选 |
| **M4 PIT / known-at 缺失** | #18,19,20,21,22；数据层覆盖 #11,#12 间接 | CA cutoff 审计：未来 ex 2,279 条中 **1,959 条公告日期晚于 cutoff**（`ANALYSIS.md:16`）；2025 状态 `history_known_at=UNKNOWN`；沪深300 mtime 晚于业务日，无法证明盘前可得 |
| **M5 纸面 ≠ 可交易（执行/成本吃掉 alpha）** | #11,13,14,16,23 | goal：纸面 46.76% → 账户口径 5.54%，隔夜跳空 +118.5bps 被 T+1 开盘系统性交出（`goal/REPORT:88`）；JKX I5 摩擦 2.7% 吃掉 +0.95% 毛利（`seven_routes:15`）；每日触发费用×14~19（`STRATEGY:38`） |
| **M6 预测对象错了（IC 提不动绝对收益）** | #2,4,6,7,8,16,18(间接) | 恒等式 `IC(pred,true) ≡ IC(pred,true−m_t)`，IC 对绝对涨跌"天生不可见"（`prediction_target:13-14`）；2025 长仓 **70~82%** 收益来自模型不预测的 m；截面损失只提 IC，top10/top200 绝对收益差 CI 全含 0（`:38`） |
| **M7 工程/数据阻塞（非策略问题）** | #18,19,20,21,22,25,26 | W1 碎股 debt、2025 CA 未知登记日、8 个 W1 版接口未回收、沪深300 指数止于 09-30 |

### 3.2 三个结构性共性（比单个模式更重要）

**共性 A：所有"高收益"都站在四个支点上，缺一即崩。**
支点 = ① 20~100 只持仓（换取分散与低方差）② 单一行情（2025 牛市 / 2021H2 / 电子行情）③ 事后选定的阈值 ④ 纸面 close 口径。W2 的 B1 +23.6794% 是唯一例外（5 只持仓、机械账本核平），但它同时是**唯一一个还没被证伪也还没被验证**的点——状态仍是 INCOMPLETE/BLOCKED。

**共性 B：IC 与收益之间的断裂是系统性的，不是某个模型的问题。**
`docs/prediction_target_and_tree_2026.md:89` 写"所有模型 2026 截面 IC 落在 0.061~0.083，无人突破"；而同期 target 年化 -6.99%~+2.25%。树模型 IC 最高（0.1050/0.0830）但净值 1.002~1.015。**说明瓶颈不在排序能力，而在"m 不可预测 + 成本 + 持仓数"三者。** 因此继续优化 IC 是**已证明无效的方向**。

**共性 C：失败大多集中在"从信号到账户"的最后一公里，而非信号本身。**
按投入产出看：信号侧（IC 0.05~0.10）已相对稳定；崩点全在执行侧——碎股（#18）、CA 登记日（#19）、隔夜跳空（#11）、换手（#12,13,23）、成本（#14）。三天工程 90% 时间花在 #18-21 的工程闭环上（`three_day:107` 自述"时间主要花在执行工程和 W1 碎股分支，策略证据产出不足"）。

### 3.3 已被否证、不应再加回的东西（负面清单）

- **方向择时门（m_t / 双塔 / hgb 门）**：三类独立证据（AUC CI 含 0.5、引擎 -35pp、双塔 -42pp）一致为负。`final_delivery:150` 明确"方向择时 m_t 门已有负向证据，不应加回候选"。
- **每日触发式调仓**：触发率 96%+，纯为噪声交税。
- **高换手 rolling**：-43.3%/-15.3%。
- **单票胜率 75%**：数学不可达（需 IC 0.35，实测 0.075）。
- **纯回归损失（pure_reg）**：分类头无梯度，Val Acc≈1/52。
- **强买门槛 t=2%**：与 t=0 逐位一致，完全无效。
- **JKX 图像线**：成本 10 倍、2026 更差、已关闭。

---
## 4. 明确标注："失败"≠"证伪"——未完成清单

这一节是本次梳理**最重要的边界**。材料里混用了"失败/中断/INCOMPLETE/BLOCKED/证伪/未验证"等多种状态，容易被下游误读成"策略被证明不行"。逐一校正如下。

### 4.1 必须读作"未完成"而非"证伪"的项

| 项 | 真实状态 | 为什么不能算证伪 | 依据 |
|---|---|---|---|
| **#18 W1 四策略** | INCOMPLETE（中断） | 中断发生在**除权处理**阶段，不是收益结算阶段。四策略的持仓、成本、信号本身没有被评估过。"没有收益数字"≠"收益为负"。中断原因（碎股不可表示）是**券商/中登现实约束的忠实反映**，属正确 fail-closed | `eight_windows_second_audit:7,25,71`；`three_day:78` |
| **#19 2025 A/B** | NOT_EVALUABLE（中断） | 两账户各持 1 只票时因**未知 CA 登记日**保护性停止；`main_end_nav=null`。中断时 A 仍持 000601.SZ 33,600 股（成本 5.76），B 持 000506.SZ 23,600 股。**没有终值就没有胜负**。且 000601 的 2025-08-05 半年报摘要已明确"不分配"，**守卫可能是误判**（但原件未闭合，不能定论） | `validation_2025_ab_v2_abort_audit:15-17`；`three_day:94` |
| **#20 W1 prefix/ceil 修复链** | 工程 BLOCKED / 证据 LOCKED | fix5 的 mini 质量门 **PASS**（94+46 项测试、Ruff/Pyright 全过，reverify4）——已修好的部分是真修好。挡住的是**可信 pin 与真实运行**，不是策略结论。**"mini PASS"不可扩大为"生产 proof PASS"，但同样不可反推为"策略不行"** | `reverify4/REPORT:7-10`；`fix5/REPORT:19-25` |
| **#21 W1 CA cutoff PIT** | 主动停止（未启动） | 4,812/4,812 哈希 PASS，是**成功的**机械校验。停止理由是"证据不足就 fail-closed"，属正确行为。`outputs/` 不存在＝什么都没算，不是算出来不好 | `FINAL_STATUS:1-7` |
| **#22 2026-09 干净考试** | NO-GO（考试没开考） | 指数文件止于 2026-09-30，没有基准就无法比较；无事前冻结信号就无法防回填。**这是"考场没建好"，不是"考生不及格"** | `prospective_exam:7-14` |
| **#25 全量训练** | 未启动 | 只有 20 股 1 epoch 冒烟，RankIC +0.13 vs -0.09 被自认"1epoch 噪声"。**base vs dual 在全量上从未比较过** | `full_train_todo:1-4` |
| **#26 双头/open-open 任务** | superseded | "未执行即被取代"——后续提交直接实现了同等功能。**没有产生任何否定证据** | 两个 `HARNESS_PROGRESS:4` |

### 4.2 必须读作"真证伪"的项（有统计检验支撑）

| 项 | 证伪强度 | 关键证据 |
|---|---|---|
| **#7 m_t 方向** | **强**：bootstrap 95%CI `[0.4968,0.5824]` 含 0.5；long-flat edge CI `[-0.00005,+0.00963]` 含 0；12 种方法一致收敛 | `m_research/REPORT:89-92` |
| **#8 双塔方向门** | **强**：离线 P(>0)=0.012，引擎 -42pp，双口径一致 | `m_research/REPORT:167-171` |
| **#6 市场择时** | **强**：2025/2026 跨年相反 | `prediction_target:53-56` |
| **#16 胜率 75%** | **强（数学）**：信噪比 0.1 vs 需求 0.67 | `retail_winrate:38-44` |
| **#1 52 类塌缩** | **强**：acc 9.75%、精确率 0.0028 | `goal/REPORT:5-7` |
| **#23 E0 "最优"** | **强**：剔除电子后整体 -34.5，4 笔交易支撑 | `ATTRIBUTION_REPORT:92-100` |
| **#12 rolling 高换手** | **中强**：两 fold 一致为负 | `goal_repro:23-24` |
| **#13 每日触发** | **中强**：96% 触发率是机制性结论 | `STRATEGY:38-43` |

### 4.3 灰色地带（既非证伪也非可用）

- **#9 波动缩放**：信号显著（IC +0.1787，CI 不含 0），但组合层 Sharpe CI 含 0，且**引擎版从未跑**。应读作"**风险控制假说，未经交易验证**"，不能读作"波动有用"或"波动无用"。
- **#11 goal 分散版**：纸面 46.12% / 延长段 +7.06%（2026）看起来不错，但 100 只持仓违反 ≤10、无 ST/退市处理、旧口径、资金 200 万与 W2 不同。应读作"**方法线索，非本目标候选**"。
- **#2/#4 主模型与树**：绝对收益为负（-6.99%/+0.23%），但**这是烧样本上的结果**。它们证伪的是"该模型在 2026 该区间能赚绝对收益"，**不能证伪模型本身的排序能力**（IC 0.061~0.105 是真的）。
- **#5 precision 规则包**：VAL 有效、2026 全塌。应读作"**跨 regime 未验证**"，已进待验收队列。

### 4.4 一个容易踩的混淆：W1/W2 "八窗全部 INCOMPLETE"

`final_delivery:91` 与 `eight_windows:7` 都写"八个窗口全部为 INCOMPLETE，实际税后目标资格 **0/8**"。这句话的正确读法是：
- **W1 四窗**：中断 → 无数字 → 不能判胜负（未完成）。
- **W2 四窗**：**有完整数字**（+23.6794%/+16.9639%/+7.8805%/+7.2273%，峰值 5 只，账本核平 2.33e-10），但仍被标 INCOMPLETE——原因是 **PIT/税务/来源未认证**，不是账本算错。
- 所以"0/8"是**验收资格计数**，不是"成绩 0 分"。把 W2 的 +23.68% 说成"策略失败"是错的；把 W1 的中断说成"策略亏钱"也是错的。

---

## 5. 一页总结

**没被证伪、但也没被验证的唯一候选：W2 的 B1/S1/S2/C70 四策略**（5 只持仓、机械账本核平、全部正收益且超沪深300）。它的问题全是"证据资格"而非"数字为负"：PIT、真实税务、CA 来源时点、coverage 缺口（missing 15,620 / unknown 16,605、`source_known=false`）。

**已被证伪、不应再投入的方向**：方向择时（三类独立证据）、高换手、20 只以上持仓、单票高胜率、纯回归损失、JKX 图像线、E0 配置优选、每日触发。

**唯一还站得住的下一步方向**（材料共识，非本次新提出）：截面 α 排序 + 低换手/惯性 buffer + **硬性 ≤10 持仓**，在 2026-09 后干净样本上一次冻结考试（`final_delivery:150`、`research/README:22-26`）。且必须先把"电子行情式单行业运气"排除掉（`ATTRIBUTION_REPORT:100` 建议的行业中性复测）。

---

## 附：证据路径速查

| 主题 | 路径 |
|---|---|
| 三天总稿 | `D:/code/cnn_full_20260905/cnn/docs/research/three_day_strategy_report_20261029.md` |
| 最终交付 + 有效性矩阵 | `D:/code/cnn_full_20260905/cnn/docs/research/final_delivery_20261030.md` |
| 预测目标与树模型收口 | `D:/code/cnn_full_20260905/cnn/docs/prediction_target_and_tree_2026.md` |
| m_t 全套（方向/幅度/双塔/波动） | `D:/code/cnn_full_20260905/cnn/research/m_research/REPORT.md` |
| goal 旧线 | `research/goal/REPORT.md`、`research/goal/STRATEGY.md` |
| goal_repro | `research/goal_repro/REPORT.md` |
| 研究注册表（状态图例） | `research/README.md` |
| 八窗对账 | `<Temp>/eight_windows_second_audit_20261028/audit.md` |
| W1 prefix 独立审计 | `<Temp>/w1_real_prefix_independent_audit_20261029/REPORT.md` |
| W1 ceil 根因 | `<Temp>/w1_ceil_failure_root_cause_20261029/ROOT_CAUSE.md` |
| W1 fix5 + reverify4 | `<Temp>/w1_prefix_fix5_20261028/REPORT.md`、`<Temp>/w1_prefix_independent_qa_20261028/reverify4/REPORT.md` |
| W1 CA cutoff PIT | `<Temp>/w1_ca_cutoff_availability_20261029/ANALYSIS.md` |
| 2025 A/B 中断 | `<Temp>/validation_2025_ab_v2_abort_audit_20261029/REPORT.md` |
| 2025 输入快照 | `<Temp>/validation_2025_local_inputs_20261029/FINAL_REPORT.md` |
| 行业归因（E0 证伪） | `docs/agent/task/20260916_0010_turnover-industry-attribution/ATTRIBUTION_REPORT.md` |
| 既有样本盘点 | `<Temp>/existing_oos_evidence_inventory_20261028/现有样本盘点.md` |
| 干净样本可行性 | `<Temp>/prospective_exam_feasibility_20261028/report.md`、`<Temp>/clean_exam_data_inventory_20261028/clean_exam_inventory.md` |
| 收口审计 | `<Temp>/RESEARCH_CONSOLIDATION_AUDIT_20261030.md` |

> `<Temp>` = `C:/Users/yanwen/AppData/Local/Temp/opencode/`

**本报告只读完成，未修改/删除任何文件，未执行任何 git 写操作。除本报告外未产生新文件。**
