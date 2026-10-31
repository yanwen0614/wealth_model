# Staged 策略最终独立只读 QA

## 裁定

**FAIL（一项确认的 fail-closed 缺陷；生产来源绑定另待最终 runner manifest 验证）**。owner worktree 冻结为 `5e384e0cce8078f1f4691aeca13dedda265e286c`，以下源码/测试六文件在审查前后 SHA 相同。结果只针对这些文件 SHA，不推断 owner 后续状态。

审查模型：GPT-6 Luna（当前会话模型）。源码/测试审查不读 memory、lock、wheel WIP；按用户后续澄清，仅只读 owner delivery 文档核对接口/runner范围。未改 worktree/env/Git，不运行收益或大数据。

## 15 条 oracle 判定

1. **PASS** — free_cash 用 available_cash 减承诺；旧损失后现金不足时 open_episode 拒绝（allocation.py:200–205,244–255；测试178–183）。具体跨四周期/活动单冻结例为本 QA 独立夹具。
2. **PASS** — commitment 按真实BUY借记递减，C70 cap=.7B，余款到关闭释放（allocation.py:257–259,604–610,627–633；测试260–281）。
3. **PASS** — t0 被拒后 t3/t6 原日期继续（strategy.py:372–384；测试175–207）。
4. **PASS（按用户澄清）** — `buy_eligible=False` 门控所有新提交的 BUY 意图，包括存量 episode 的 t3/t6 加仓；不改变排名或 SELL。ready 且 false 的 E 日旧计划禁 BUY 符合裁定；持续rank与S2区间仍独立检查（strategy.py:255,282–289）。保留探针 `existing_t3_buy_gate ineligible orders 0`，现判为预期行为而非缺陷。
5. **PASS** — t6 close 先决定 tranche 再 finalize；advance 不做关闭，core snapshot date 检查新鲜度（allocation.py:406–419,696–719；strategy.py:183,215）。
6. **PASS** — 关闭要求全部 tranche terminal、plan 日期对应的新鲜 snapshot、positions/locked/权益/活动单代码全清（allocation.py:696–719；测试155–176,463–486）。
7. **PASS** — 仅同代码非 CLOSED episode 阻重开；其他代码不受 exit_pending 全局阻断；占位用代码并集（allocation.py:244–255；测试525–534；strategy.py:174–182,332–349）。
8. **PASS** — 独立 core runner 部分BUY探针：1 fill、terminal=partial、tranche=partial、次日无重排BUY；执行采用真实 `pending.pop` core runner。探针输出/脚本在本目录。
9. **PASS** — buffer 分支不读排名、只取消未来份额并生成退出SELL；E（最后决策日）阻 BUY，E2E/maintenance 测试239–266,305–378。
10. **PASS** — T close raw close±4.5%按 tick 向内取整；固定股数；按次日成本 resolver 或配置 worst-case fees（strategy.py:386–427；测试116–173）。T 官方界不夹价；core执行日独立裁决。
11. **FAIL / production binding BLOCKED** — `source_id="unknown"` 被视为完整来源并实际生成 BUY；`RankingSnapshot` 只验非空字符串（strategy.py:43–60），MappingSource 只验日期/complete（99–106）。独立探针最小路径：complete=true、AAA rank=1、buy_eligible=true、有效close，`source_id="unknown"` 产生1张BUY。生产侧 strategy API 由调用方注入 RankingSource（delivery文档46–49行）；runner.py:381–405仅透传adapter provenance/manifest，本批没有 `RankingSnapshot.source_id` 到最终 manifest 的绑定证据，需最终runner manifest验收。持仓代码缺rank不发退出/无专门unknown因（250–261）；非日历日期静默无单（168–169）。
12. **PASS** — event/fill/snapshot 重放幂等、异载荷与乱序失败原子性有测试（bridge.py:61–83；allocation测试76–97,283–311；bridge测试67–100）。同日重复策略调用探针第二次0订单。
13. **PASS** — 同一 registry 固定初始 C 且无半年自动 reset；活动周期/账户状态连续。跨半年专用测试缺失，结论由实现结构确认（allocation.py:151–206,236–260）。
14. **PASS** — E日完整排名仍用于退出，E收盘向首buffer开盘SELL，使用持仓−locked、保留 episode/order/limit；buffer禁BUY。实 runner E2E测试305–339及buffer测试341–378。
15. **PASS** — 正持股/锁仓/权益/活动单代码去重并集≤10后才开新代码，SELL未确认的活动代码占位不腾位（strategy.py:174–182,332–349）；分项状态可查询。十码边界无专用策略测试。

## 缺陷交接（请主会话 resume 唯一 owner 修复）

- **source 占位放行**：oracle第11条与rulings第9行要求来源 unknown fail closed。当前 `source_id="unknown"`、complete=true、AAA rank=1、raw close有效会发出1张BUY。至少拒绝空白/`unknown` 等明确占位并记录原因；生产来源与 runner manifest 的绑定另在最终runner验收中核验。
- **buy_eligible 语义澄清**：初稿曾把存量 tranche 的拒单列为 BUG；依用户补充裁定撤销该缺陷结论。反例保留为预期行为，不能要求放宽 E 日及其他 BUY 资格门。

## 验证门禁与冻结 SHA

- 53 unittest：PASS；Ruff六目标文件：PASS；目标 Pyright：0 errors/0 warnings（第一次未传 interpreter 导致第三方解析失败，补 `--pythonpath .venv\Scripts\python.exe --project .` 后通过）。
- core wheel SHA-256=`76cc80e5fa8fa39513a21876137a5e1c99e001b7c74801a78b76345554d72470`；private venv import 指向该 tree `site-packages/backtest_core`。
- 精确命令、六个源码/测试起止 SHA、HEAD、diff范围见 `FINAL_QA_MANIFEST.json`。
- 未跑真实市场收益；E2E仅用冻结 core runner + synthetic market/account。
