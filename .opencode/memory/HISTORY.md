[2026-09-03~09-13] 归一化基调 per-code，E1-E4 对照实验完成，context warmup 修复（标签日 95→154）
[2026-09-14] redesign: FEATURE_GROUPS(P/R/N/G)+52列+shared mask、ColumnRule registry、PerCodeGroupedScaler v4、rolling scope e0..e5、train/CLI 适配；E0-E5 六臂训练 E3 最优(RankIC 0.0441)
[2026-09-14~15] 回测口径升级(A股费用/指数基准/小TopN/avg_cash_ratio)；E0 relative 设为 baseline
[2026-09-20] 建立三分评估规范(eval_three_way)，新增 cs_rank 截面rank特征；GBDT 截面 rank 生产模型 test RankIC 0.075，确认 75% 单票胜率不可达(天花板 52-58%)
[2026-09-20] 特征工程/滚动重训/风险 overlay/空仓/XGB-GPU+DNN 研究完成；集成共识天花板 0.544；指数 MA40~80 趋势过滤近乎免费降 MDD
[2026-09-21] 全市场截面扩展/截面因子拓展/自主冲75%/xgb新目标全部失败，75%不可达收敛。引擎杠杆 bug 修复。ASL 证伪(p*=0.575梯度偏移)。提交纪律确立。
[2026-09-22~23] H10 全链路：指数口径审计(ew等权唯一合格)、冻结A 2026 样本外(V1/V2 NAV 1.1448/1.1174)、预注册方案A唯一通过、选项二 REJECT、选项一固化前验证 PASS
[2026-09-28] 主仓整理：merge origin/main(a8866a7)、backtest-core 克隆、logs 大扫除(340→76)、paper_jkx 源码入库、adapter 为唯一回测路径
[2026-09-30~10-01] 三组建模完整评估(B截面最优)、JKX I30-color 实验定论(排序有信号但绝对收益不如主模型)、α vs 市场项 H1-H6(信号α主导)
[2026-10-02~03] 损失对照(C/D/E截面损失RankIC显著优于CE，top10/200绝对收益均不显著)、早停改RankIC(对CE变体+0.0002近乎无效)、JKX图像线停止、主模型A补跑2026、树模型同口径验证(IC全面优但target净值属噪声区)
[2026-10-05~08] 全模型α归因(树模型2026唯一守住正α)、精确优先(VAL提至0.60-0.64,2026全塌)、m_t可预测性系统研究(方向/幅度不可行,仅波动可作风控候选)、完全分离双塔(方向门证伪,波动定仓不显著)
[2026-10-23] 创建 decile_diagnosis.py(十分位收益诊断+驼峰检测), 16单测PASS+ruff零告警[2026-10-25 13:01] 3070 训练任务完成：5 轮迭代，最佳配置 excess+F53 Val Loss 0.0480
[2026-10-25 13:15] 2026 回测：Round 4 模型 top20 年化+2.54%，全正收益，跑赢沪深300 4.4%
[2026-10-25 22:40] 最终策略方案：target8+自信号择时，Sharpe 2.96/年化40%/回撤13.4%
[2026-10-25 23:16] Walkforward 回测审计：涨跌停 lookahead bias 修复、实际持仓≤10 约束、W1/W2 H10 标签端点核验、LABEL_MODE 配置传递不匹配
[2026-10-26 03:50] 更新记忆：补充 Luna NO-GO 硬门槛细节（费率断点/复权 notional/终端残仓/2026 因子缺失/身份追溯）；日期/标签修复七关 PASS；公司行动契约；身份模块实现及审查；费用/终端接入真实现金路径；半年绩效锚定与退出缓冲规则；价格血缘核心发现
[2026-10-26 04:30] 记忆更新：W3 workers=0 完成5轮(最佳epoch3 val 0.057885)；checkpoint不存随机状态/早停计数无法精确续训；模型返回(logits,aux_loss)元组；W1/W2/W3超参一致；Windows 16GiB workers=4内存约束确认需workers=0
[2026-10-26 08:02] 新增：无标签全期信号脚本开发进展（generate_walkforward_signals.py + 测试），W3最佳checkpoint确认，信号生成契约（首context复现、float32、中文、缓冲区规则），修正Key Facts中W3轮数
[2026-10-26 08:34] 信号脚本独立QA全通过（8 tests+Ruff），W1两代码小投影数据准备完成，W1小推理技术验证执行成功
[2026-10-26 09:10] 价格血缘溯源完成（量额1000倍差解释+交叉验证）；后复权2021-2025最小可用区间确认（缺同日因子仅微额派息≤0.005元）；history_status字段映射解码（退市警示=现金除息日）；幸存者偏差确认（5只退市股训练F60为0行+raw文件缺）；5财务列PIT审计不能PASS；18两融列审计进行中
[2026-10-26 10:21] 新增：F29纯技术特征主方案确立（取消F30/mask接口需求）；唯一W1 F4 OHLC对照训练已启动(run_20261026_100509, epoch1完成loss 0.0466/0.0505)；W3训练总轮数=30、weight_decay=1e-5来自run_cfg等CLI细节确认
[2026-10-26 11:33] Z库公司行动pretax账务核验完成；独立复核BLOCKED（三个缺口）；corporate_actions成本缺口确认（pretax only）；最小税务接入计划要求明确
[2026-10-26 14:45] 分批组件 staged_allocation.py TDD 修复完成；核心契约：唯一fill_id、core快照权威、cash不自加减、exit_pending不因advance清除；生产桥接仍blocked（缺回调/order_id/fill_id）
[2026-10-26 14:47] 添加Luna只读审查报告完成、4.5%执行政策审查完成、staged_execution_bridge_plan设计启动等事实
[2026-10-26 15:37] 更新：DS盘点已产出 state_evidence_W1_ds_v1（20文件），HDF IS_WD_SEC/IS_XR_SEC 为字符串 dtype 致统计bug；来源契约/补采计划 d46655d 归档；Luna ses_e8b7913a 暂停实现转为 DS 独立语义QA
[2026-10-26 20:02] 完成18两融列时点审计（236/236 T+1对齐探针通过）、backward_factor日期更正（全表2026-09-29）、研究归档与现有源恢复核查入记忆
[2026-10-26 20:25] 新增: core基线合并主区/000001机械回放完成/core观察器实现/并行隔离规则正式化/基准更正/technical29审计完成/历史状态语义澄清
[2026-10-26 21:41] 新增W1 HDF语义跟进三段裁定、000001.SZ日线字段GO/机械回放条件GO/排队NO-GO、SQL稀疏表源码覆盖限制确认
[2026-10-26 22:04] 限价订单实施方案只读审查：确认 raw reference_price 始终为空、core MarketBar 无法定价格边界；文档写入 approved temp dir，未改仓库/env/git。
[2026-10-27 09:11] Oracle独立审查15条裁定落地，策略最终QA发现source_id='unknown'能生成BUY为真实缺陷，buy_eligible门控存量t3/t6加仓裁定为符合预期
[2026-10-27 12:05] Updated: lite_general constraint (session tracking + training tracking only); worktree cleanup enforcement; strategy merged 6676b57 (304 tests); W2 signal independent verification (538K rows, 125 days); 补证首批核验通过 (SDK隔离环境, 2股2窗pre-check PASS); pruned granular historical session IDs
[2026-10-27 13:11] 2026-10-27 修正：assemble_state.py 全量 in-memory all_rows 改为逐码流式；row_hash 改为 canonical JSON；source_sha 引用 manifest 而非自算；flag 值保留原始字符串；probe_sqlite 限定白名单两表
[2026-10-27] 独立审计发现 IS_WD_SEC 语义反证：quant 映射"退市风险警示"被现金分红日样本证伪；IS_WD 实际为除息、IS_XR 为除权
[2026-10-27 16:49] 补采审计完成 + 暂停上市缺口核实到公告原文 + 科创板数量规则确定 + 数量规则模块编码完成(待审查)
[2026-10-27 22:27] 公司行动整合计划 T01–T06 最小闭环编码完成：ctx→recorder→bridge 接线、CA hook、finally 审计、数量 resolver、378 项回归通过；prepare 内存修复（v1 卡 569 代码/1.5GB → 按代码懒加载+streaming coverage）；解释器绑定 wheel 版 core 路径；gap 文件路径校正；4,424 代码板别映射配置生成
[2026-10-28 01:25] 全量prepare三次失败根因闭合：v8跨窗empty_codes缺陷已修、v10 coverage日外层循环瓶颈已修、v6/v9无声消失=工具会话作业对象回收；长任务须WMI脱离或tmux后台（psmux起始目录是主目录，必须cd工作树）
[2026-10-28 02:08] T01-T06收口：v12全量prepare-only经tmux后台首次完整成功（4424码/manifest/EXITCODE=0/34分钟），378单测+Ruff+Pyright全过，源码hash冻结，交独立QA
38: [2026-10-28 12:50] 八窗机械回测完成全部INCOMPLETE：W2四策略净值+7~24%（同期沪深300 -5.44%），W1全同一次送转中断（2021-06-08）；送转比例有旁证（0.4002532匹配年报转载索引）但碎股入账无正式依据；独立核查仍在进行
[2026-10-28 13:09] Memory review: conversation was read-only quantitative analysis initiation with no new conclusive facts; no memory changes needed
[2026-10-28 13:25] 用户明确会话默认 Luna、连续受阻超过三次才用 Sol；已派会话由 lite_general 跟踪；八窗对账与公司行动证据更新。
[2026-10-28 13:54] 取得并核读新易盛2021-030官方PDF，确认精确转增、现金及碎股排序规则；虚拟账户最终获配仍未知。
[2026-10-28] 确立整体目标：自主探索验证可执行股票策略，扣费后非负收益、严格跑赢大盘、持仓≤10只
[2026-10-29 00:38] 已归档校验并退役数量规则、旧runner和旧CA工作树；W1前缀fix5在截止后待独立复验。
[2026-10-29 21:53] 添加 000601.SZ 公司行动事件审计记录（id 17916/17917/17918 定向公开取证，官方PDF部分未核实）
[2026-10-30 01:07] 新增 git post-checkout 钩子：worktree 自动链接主 .venv（实测 junction 会被 remove -f 删穿，改优先 symlink）
[2026-10-30 08:38] P0-2 完成：18 个 W1/2025 研究源码从 opencode.db 恢复到主区并提交（8cd25a9 + ff7e606 lint noqa），确认 7112BEDE 中间态无独立副本但可从 evidence2.json 无损复现
[2026-10-30 13:08] Q3 可复现性评估已执行，报告外部保存
[2026-10-30 21:16] 整理项目文档：建立 docs/README.md 文档地图、迁入 33 份 Temp 过程草稿到 source_drafts、固化本轮整理全部结论与待办到项目记忆
[2026-10-30 22:17] 工程整理最终轮：文档地图建立、docs/research/review_20261030 重组（q1~q5删）、backtest/cnn_adapter/拆3子包（ca/w1_prefix/validation_2025）、paper_jkx/logs和tree_verify/tree_rebuild删除（共19.5GB）、T18轮转递归扫描修复、14条放弃路线代码删除（b9254bb）、训练数据黑名单机制（排除0只）、Temp md全部迁入仓库、核心HEAD更新至c879dee
[2026-10-30 23:05] 主区 6 个最后脏文件全部提交：审计脚本标签端点核验 07d1831、三份 20261026 研究文档 a5a7bf2、memory 随同一并入库；工作区清零
[2026-10-31 00:02] 完成 P0：opencode.db 冷备份（自包含单文件/integrity ok）与 4 个 scaler pkl 异盘+身份 JSON，均落 G:\backups\cnn_full_20261030\
