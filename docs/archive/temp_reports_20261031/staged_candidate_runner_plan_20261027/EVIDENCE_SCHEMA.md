# 保存证据 Schema 提案

每次运行一个新目录，immutable manifest 指向以下 UTF-8 JSONL/Parquet 文件；日期、金额单位和版本必须写入 manifest。所有逐日/逐单记录带 `run_id, mode, window, policy, trading_date`。

## manifest.json

`schema_version, run_id, run_status, result_scope(restricted_daily_mechanical|performance_eligible|incomplete), created_at, source_commits_and_dirty, imported_module_paths_and_sha256, core_wheel/version/schema, python/dependency_versions, registry/oracle/strategy/bridge SHA256, checkpoint/cache/raw/state/corporate_actions/calendar/benchmark SHA256, config_hash, initial_capital, tranche_budget, tax_policy, tax_completeness, cost/slippage/capacity/limit profile, rank rule, window definitions, anchors, E dates, buffer dates, buy_forbidden_execution_dates, benchmark name/price-return endpoints, coverage counters, failure_assertions`。

## daily_account.jsonl

逐交易日包含：`date, phase(anchor|signal|buffer|end), benchmark_close, cash, available_cash, blocked_cash=cash-available_cash, positions[{code,shares,locked_shares,close,market_value}], receivables[{id,amount,pay_date}], pending_cash, unlisted_entitlements[{id,code,shares,value,listing_date}], active_orders[{id,code,side,remaining_shares,execution_date}], held_code_count, entitlement_code_count, active_order_code_count, distinct_occupied_codes, nav, nav_identity_error, active_commitments, free_cash, active_slots, episodes/tranches summary, signal_universe_count, ranked_count, buy_eligible_count, unknown_state_count, buy_allowed, buy_block_reason`。

## decisions_orders_fills.jsonl

每条决策/订单/成交/终态一行：`event_id, sequence, signal_date/time, execution_date/time, code, full_universe_rank, exp_ret, status_ready, buy_eligible, source_state, source_version, reference_price, absolute_limit_up/down, order_id, attempt_id, fill_id, episode_id, plan_id, tranche_id, side, shares_requested/filled, limit_price, tif_semantics=single_day_core_pending_pop, order_status, reason_code, base/fill_price, amount, commission, stamp_tax, transfer_fee, slippage_cost, participation, pre/post cash, cash_debit, core snapshot id/sequence, raw bar hash, evidence_class(verified|unknown|assumption), source_refs`。

## policy_summary.json

按策略、窗口、资金规模报告：`主半年close收益/金额, benchmark同期收益/金额, 超额, buffer后收益与同时间基准, buffer收益不得覆盖主结果, turnover/费用分项, cash/持仓/locked/应收/未上市权益/活动单终态, max held codes, max occupied union, 预算峰值, rejected/unknown按理由计数, opportunity denominator/covered/unknown/verified比例, W1/W2各自 verdict, overall status(PASS|FAIL|INCOMPLETE|BLOCKED), assertion failures`。收益口径须用实际NAV端点；禁止用每日/成交盈利替代半年端点验收。

## validation_failures.jsonl

`assertion_id, severity, date, code, order/fill/episode ids, expected, observed, source_ref, blocks_run, message`。任何身份漂移、未授权限价推导、预算透支、排名重排、BUY越禁买日、SELL丢失身份、超过持仓上限、现金/NAV不守恒、forced exit、缺失快照均有可机读失败记录；阻断性错误令 run_status=FAILED，禁止产出绩效 PASS。
