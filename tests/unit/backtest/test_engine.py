"""已退役：legacy 引擎单测拆分为新框架语义测试（本文件不承载任何测试）.

为什么保留这个空文件：原 ``test_engine.py`` 的 13 个类 / 52 个用例全部末调用
``backtest.engine`` 的守卫入口（``run_backtest`` / ``run_backtest_target``），
迁移到 ``backtest.cnn_adapter`` 后用例已分散到下列文件。此处仅留去向索引，
避免后来者以为覆盖丢失；索引可按需删除，覆盖不受影响。

迁移去向（测试文件 → 详见各文件模块 docstring）：

``test_metrics_and_benchmark.py``
    ``TestFeeModel``（4）→ ``TestFeeModelArithmetic``（KEEP：冻结费率常量算术）
    ``TestNavMetrics``（2）→ ``TestNavMetricsLegacy``（KEEP：生产函数）
    ``TestBenchmarkIndexNav``（4）→ 同名类（KEEP：生产函数，沪深300 基准）
    新增 ``TestMetricParity``：legacy ``nav_metrics`` 与 core ``evaluation.metrics``
    在 ``rf=0/ddof=0/ppy=252`` 下逐值一致（指标口径未随引擎切换漂移）

``test_cnn_adapter_rolling_semantics.py``
    ``TestRunBacktest.test_cost_exact_deduction`` → 逐笔费用恒等式
    ``TestRunBacktest.test_equal_weight_allocation`` → ``test_five_names_equal_weight``
    ``TestRunBacktest.test_open_open_return_exact`` → ``test_filled_price_ticks_against_order_side``
    ``TestRunBacktest.test_skip_limit_up_and_redistribute`` → ``test_limit_up_name_skipped_and_slot_stays_cash``
    ``TestRollingFeeModel``（3）→ ``test_rate_branch_and_min_commission_branch`` /
    ``test_invalid_fee_inputs_rejected``（``test_holdings_ret_net_uses_fee_model`` 并入费用恒等式）
    ``TestBenchmarkAndEdges.test_all_nan_path_empty_batches`` → ``test_missing_price_skipped_and_not_counted_as_limit_up``
    ``TestBenchmarkAndEdges.test_zero_samples`` → ``test_zero_samples_rejected_loudly``
    ``TestBenchmarkAndEdges.test_single_stock_topn_exceeds`` → ``test_single_name_uses_full_cash``
    ``TestBenchmarkAndEdges.test_all_limit_up`` → ``test_all_names_limit_up_leaves_nav_flat``
    ``TestLookaheadAndOrdering``（3）→ ``test_future_rows_do_not_change_past_snapshots`` /
    ``test_tie_break_prefers_lower_code`` /
    ``test_missing_price_skipped_and_not_counted_as_limit_up``
    ``TestAvgCashRatio.test_rolling_avg_cash_ratio_zero`` → ``test_rolling_cash_ratio_upper_bound``

``test_cnn_adapter_target_semantics.py``
    ``TestRunBacktestTarget``（7 项）→ ``TestTargetBuyBandAndHolding`` 同名语义用例
    ``TestRunBacktestTarget.test_zero_samples_target`` → ``TestTargetCashRatio.test_no_signals_holds_all_cash``
    ``TestTargetFeeAndExit``（7 项）→ ``TestTargetExitRules`` / ``TestTargetFeeAndCapital``
    ``TestStrongBuyGate``（4 项）→ ``TestStrongBuyGate``（含现金口径差异说明）
    ``TestAvgCashRatio``（其余 4 项）→ ``TestTargetCashRatio``
    新增 ``TestTargetHoldingCap``：``_MAX_HOLDINGS=10`` 硬上限（legacy 无此概念）

``test_cnn_adapter_regression.py``
    原「legacy vs 新引擎对照」改为单侧新引擎基线回归（执行顺序 / 费用恒等式 /
    成本量级 / 无异常拦截 / 指标可复算）。

DROP（语义已被历史否决或新框架不存在，理由见对应新文件 docstring）：
    ``TestLimitUpMask``（2）—— 近似乘数 1.098/1.198 已被 ``CnnMarketDataProvider``
    的分网格精确判定取代，覆盖在 ``test_cnn_adapter_market.py::TestLimitGrid``。
    ``TestBenchmarkAndEdges.test_benchmark_equal_weight_no_limit_filter``（1）——
    等权全市场基准已被历史否决（基准改为沪深300），新框架无 ``benchmark_nav``。
    ``TestRunBacktest.test_five_batch_rolling``（1）—— legacy「每日投 nav/horizon、
    horizon 批重叠、退出日一次性实现」的账本结构在新事件驱动账户中不存在。
"""
