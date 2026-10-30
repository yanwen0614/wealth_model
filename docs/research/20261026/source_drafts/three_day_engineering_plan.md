# 三天研究工程计划与状态

- 授权：截至北京时间2026-10-28 23:25；不提交、推送、删除，不改记忆，每次写入≤50行。
- 2026-10-25：已读取统一控制台、根规范、cnn-harness/quant-model及W1/W2执行审计；适用模块规范由拆解/实现代理读取。
- 已有改动保留：audit_walkforward_execution.py、test_cnn_adapter_contract.py、两份memory。
- 决策：Luna NO-GO为强制门；未全部通过仅允许接口和CPU合成验证，禁止候选结果比较。

## 现有证据

- 开盘限价已使用执行日open对比历史close；target策略名额保守计入待卖实际持仓，W1/W2峰值8。
- W2期末现金852049.72363+688768.SH持仓340857=1192906.72363；3300股T+1锁定，非清仓现金。
- W1尾日09:30强平早于15:00信号；现有终端liquidation标识不能证明清算完成。
- 预测缓存W1止于6/15、W2止于12/16，缺尾部，不能验收完整半年。
- 当前费用固定现代费率；2021卖出税应0.001；沪深过户费2022-04-29起0.00002→0.00001双边。
- 后复权价格×原始整数股数与真实amount不一致，公司行动未处理，真实逐股执行尚未成立。
- 历史ADV20用于容量并不证明集合竞价深度；需开盘容量及滑点压力测试。

## 最小修复、文件占用及预计工程时间

1. 评估LABEL_MODE、no_val保留训练日期、数据工厂读数前拒绝重叠：独立Luna七关PASS并关闭；后续仅测试类型标注微修。
   占用train.py、data/dataset.py、scripts/eval_bins_mapping.py、scripts/run_eval_pipeline.py及三个定向测试。
   独立Luna定向命令50项通过。测试字典新类型错误已定点标注Any；复跑仍见一条原有pyright enterContext错误，ruff通过。
2. 成交日历史费率及断点：Luna实现中，扩展core订单费用注入，须经实际现金流水合成E2E验证。
3. 终端mark-to-market、T+1退出-only缓冲、残仓状态及每日恒等式：Luna实现中，尚未验证。
4. 每路径git SHA/dirty、关键模块及core内容hash、依赖版本、数据/缓存hash：独立Luna实现中。
5. 无标签有效信号接口：先设计并CPU小样验证，预计30–60分钟；不重构整个Dataset。
6. raw价格/调整单位及公司行动方案依赖盘点证据；未闭合前不得将代理回测升级为可执行证据。

## 可复用真实引擎接口

- backtest.cnn_adapter.runner.run_cnn_backtest：预测adapter→订单策略→core.run_account_backtest_from_orders。
- outcome.result.account_snapshots/order_results/trades保存逐日NAV、现金、持仓、订单、成交和拒单。
- evaluate_account复算指标；现有write_cnn_result仅三件套，完整审计另保留JSONL。
- 当前runner日期限于缓存覆盖；不能直接把扩展日期伪装成存在信号。
- 一次性/分批目标仓位接口暂仅设计，待主会话冻结候选后实现参数。

## 放行、测试与资源

- 必须全部通过：历史费用；价格/股数/notional一致；全期无标签信号；T+1退出缓冲禁新仓；逐日现金+市值=NAV；残仓/锁仓透明；同时间戳基准；每执行路径完整身份。
- 先RED/GREEN定向unittest，再独立quality-gate审查、ruff及定向类型检查；旧失败与新增回归分别列证据。
- 所有临时证据位于本目录；Harness三件套位于three_day_engineering_harness/。
- 本会话不占GPU，无需等待工程即可由主会话分配；W3恢复与训练队列由运营Sol专项负责，不重复检查。
- 不启动长训练、W4或策略扫描；费用/终端/身份均先小CPU合成验证。
- 价格血缘新增发现：2026-06-26 600519.SH派现28.02423元/股，但训练因子表截至2025-12-19，训练价延用旧因子且状态映射误标退市风险警示；2026缓存不得验收，待价格血缘最终报告。

## 新增公司行动接入契约

- 只读依据：three_day_corporate_actions_contract.md。raw价格/原始股数做账户现金与市值；复权训练OHLC不进入成交notional。
- 后续新增独立 CorporateActionProvider/Ledger，不复制订单撮合与费用算法；当前 core owner 文件编辑结束后再确定 hook。
- 日序：record close冻结持股；ex-date建现金/股份权益，pay-date日终才转可用现金；红股上市可卖时点未证实则采用EOD unlock压力情景。
- ex-date/reference unknown仅拒该证券当日开盘订单，按raw价留存持仓，权益与拒单分别报告，不回溯删信号。
- 配股固定不认购；原股raw盯市，reference unknown门控与权利价值/注销unknown单列，不宣称权利完整计价。
- 日终恒等式扩展到available/restricted cash、上市/未上市股份、应收及负债；现金/持仓残留和cleared分开。
- 税务真实FIFO与现金20%统一预提压力情景分开；后者不称真实税后，红股税和零股规则unknown。
- 手算锚点：000001.SZ 2021-05-14现金分红0.18元/股；300896.SZ 2021-03-16派现3.5、送转0.8。算术除权价不得冒充官方reference。
