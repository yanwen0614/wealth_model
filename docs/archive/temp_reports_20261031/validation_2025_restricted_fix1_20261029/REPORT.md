# fix1：CA 逐事件窗口化修复交付

日期：2026-10-29。唯一 owner 继续在隔离树 `validation-2025-restricted-20261029`
（分支 `research/validation-2025-restricted-20261029`，基线 `ce7d1c6`）。
响应独立 QA FAIL（P1：`ca_unsafe()` 全期按 code 预筛，期外未解事件提前禁买）。

## 根因与修复

原 `ca_unsafe()` 对任一未解权益的证券返回全局 code 集合，`qualify()` 在每个信号日
按 code 直接拒绝，不检查事件是否可能在本窗口产生登记持仓——QA 反例（rights 登记日
2025-02-03，窗口 E=2025-01-07+3 buffer，全部阶段期外）被四个信号日全部拒买。

修复为 `ca_exposure(snapshot, window)`：逐事件取全部已知阶段日期（record/ex/pay/
listing），与窗口末（含 buffer）比较后分类；不做按 code 全期预筛：

| 分类 | 判定 | 行为 |
|---|---|---|
| future_out_of_window | 全部已知日期 > 窗口末 | 不拒绝；留 `ca_flags` 风险标记 |
| timing_unknown | 无任何可用日期 | 无法证期外，仅阻该 code（ca_timing_unknown） |
| in_window_rights | 配股阶段在窗内（core 不处理配股） | 仅阻该 code（ca_in_window_rights_unresolvable） |
| in_window_unresolvable | 分红缺金额/缺总比例（strict_tax=False 下 core 不中断） | 仅阻该 code（ca_in_window_unresolvable） |
| in_window_dividend | 其余窗内分红（缺ex/record/pay/上市日等） | 允许买入，core 按实际登记持仓 fail-closed |

公告时点未证（无 event 或 announced_date 缺失）一律打
`announcement_known_at_unknown` 标记（仅留证，不影响资格）；event=None 且
record 已知另留 `implementation_not_certified`。所有事件保留
`known_at=UNKNOWN、pit_verified=false`；不虚构已实施、股数或实际税。
完整榜/原排名/分数不重排；ST 只禁新买；缺行情/状态拒单；持仓≤10 不变。

## 证据（本目录）

- `RED_fix1.log`：修复前 10 项失败复现 QA 反例与新边界（先 RED）。
- `GREEN_fix1_final.log`：修复后 24 项定向测试全绿（21 旧 + 3 新增）。
- `REGRESSION_fix1.log`：既审 8 套件 109 项全绿；`RUFF_fix1.log`、`PYRIGHT_fix1.log` 全绿。
- `FIX1_MINI_SUMMARY.json` + `fix1_final_*`：11 组真实 core mini 最终留证：
  future_rights/future_dividend 正常买入（error=null）；
  no_dates/rights/missing_cash 仅阻该码、其余 4 码买入；
  missing_ex/missing_record/missing_pay/share 买入后 core fail-closed，
  前缀完整（terminal_positions 保留 19,100 股），标签 ABORTED_AT_UNKNOWN_EVENT；
  held_susp 持有停牌保留库存不清仓；normal_regression 与修复前一致。
- `FREEZE.json`/`FREEZE.sha256`：改动与产物 SHA、生效模块 SHA、16 项既审文件复验。

## 边界与未闭合（继承并重申）

2025 为已见验证期历史回放；结果始终标 CONDITIONAL_RND / INCOMPLETE / PIT_UNPROVEN，
target_verdict=NOT_EVALUABLE。官方 2025 数量规则 PDF 404 未取得原件；条件规则仅
SZSE_MAIN 情景。000040/000584 缺 raw；268 缺状态码日原因未知；PIT、公告/实施、
实际个人税均 UNKNOWN。未运行全年 A/B；`--execute-ab` 仍须独立 QA 后显式调用。

## QA 复验入口

改动仅两文件：`scripts/run_2025_restricted.py`、`tests/unit/backtest/test_2025_restricted.py`
（SHA 见 FREEZE.json）。复跑命令与 fix1 前版本一致（`GREEN_fix1_final.log` 记录）；
mini 须用全新输出路径（run_restricted 拒绝覆盖）。完成后停止修改，交原独立 QA 复验。
