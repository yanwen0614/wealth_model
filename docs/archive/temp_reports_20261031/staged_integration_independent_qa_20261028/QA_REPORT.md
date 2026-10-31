# 整合交付独立只读 QA

日期：2026-10-28。对象：工作树 `corporate-action-fix-20261027`，HEAD `ce7d1c6e0bd64136f10759412c55f6da410f128f`。审查只读；未运行准备器、正式八窗绩效、训练或提交。

## 结论

- **VERDICT：FAIL（审查/验证证据门）**。当前整合能导入运行，定向测试与静态检查通过；v12 完整准备产物可核对到 manifest 外置 SHA、实物文件数和摘要计数。
- v12 成功退出证据未独立取得：交付总结称 stdout/stderr 日志在准备目录，但 glob 未找到相应文件；该目录仅有准备产物。总结中的 `exit_code: 0` 不能单独替代运行器退出日志/可核实进程状态。
- 不代表源码冻结失配或发现已证实的执行逻辑故障。**机械整合可运行：PASS（基于 378 backtest 单测和代码接线审查）**；**完整准备证据：FAIL（成功退出凭证缺失）**；**实际税后/绩效：未验收**。

## 准确证据路径

- 计划：`staged_production_integration_plan_20261027/PLAN.md`、`REVIEW_CHECKLIST.md`。
- 冻结哈希、交付声明：`staged_production_integration_delivery_20261027/SOURCE_HASHES_FINAL.json`、`DELIVERY_SUMMARY_20261028.json`。
- v12：`staged_prepared_inputs_20261027_v12/manifest.json`、`manifest.sha256`、`integration_inputs.json`、`coverage_W1.json`、`coverage_W2.json`、`fees_W1.json`、`fees_W2.json`、`raw_read_statistics.json`、`states/`、`raw/`。
- 实际退出日志：未找到 `prepare_v12.stdout.log` / `prepare_v12.stderr.log` 或其它 exit-code 日志。

## 哈希与准备产物

- 审查前及审查后：清单 16/16 源码及测试 SHA256 与 `SOURCE_HASHES_FINAL.json` 一致；具体逐项值以该 JSON 为准，审查后复算未见差异。
- `manifest.json` 实测 SHA256 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`，与 `manifest.sha256` 匹配。
- 文件计数：raw parquet 4,424；state shard 253。manifest `artifacts` 项 4,812；core path/hash 与交付总结声明均被保存在 manifest 中。
- Coverage W1：510,692 expected；17,029 missing bar；17,909 unknown。W2：570,696 expected；15,620 missing bar；16,605 unknown。缺失/未知保留为审计状态，不能等同全量已知。
- fees 两窗各有冻结费用配置与 resolver 来源证据；raw 逐码统计包含 source hash、源大小/行数、扫描/保留行与耗时。未重读 4GB 训练源，未覆盖准备目录。
- `source_known=False`（状态来源血缘仍待独立验收）；`actual_after_tax_target_eligible=False`。统计产物不是正式回测结果。

## 代码与数据流审查

- `staged_candidate_runner.py` 将 core observer 指向 CA context，context delegate 为 recorder，recorder 再 delegate bridge；`account_actions_provider` 取 context hook。finally 保存 CA evidence、partial states、updates/registry、错误类型/原因和 artifacts 清单。错误窗起始 mechanical status 为 INCOMPLETE。
- v12 准备按窗口构造空行情代码集，再传 `allow_empty_window`；000792.SZ 这类跨窗状态不再用全局空码判断。coverage 采用 code 外层循环，避免懒加载每个日期重扫全部状态分片。
- 排序快照来自冻结信号；Top5 coverage 保留冻结 rank/`buy_eligible`，不因执行行情缺失重排。raw provider 有 execution_end 截止；E-1→E 合法边界由 runner/calendar 与策略判断。
- 科创 rule 配置为 min 200/step 1/max 100,000；并非 200 股倍数。费用按实际执行日 resolver，冻结表从 anchor 后日历起始；初始资金 1,000,000，账户/registry/槽位及持仓使用真实 core 对象。
- 遗留边界：checkpoint 在本轮只以准备 manifest 来源 hash/已有严格加载报告引用，未加载模型；市场来源明确 unknown；CA tax/PIT/实施未知；不可宣称实际税后完成。

## 验证

- unittest：`python.exe -B -m unittest discover -s tests/unit/backtest`，378 passed、2 skipped，10.767 秒，exit 0；CNN_ALLOW_LEGACY=1。
- 定向 unittest：8 个相关模块，109 passed、0 skipped，8.494 秒，exit 0。
- Ruff：16 个冻结源/测试文件 `ruff check --no-cache`，All checks passed，exit 0。
- Pyright：8 个源文件，0 errors / 0 warnings / 0 informations，exit 0。
- 命令均用 `D:/code/cnn_full_20260905/cnn/.venv/Scripts/python.exe -B`，工作树作为 cwd；未更新环境。测试日志未另行落盘，结果由本 QA 会话工具输出记录。

## 关卡与问题

- HIGH：规范/边界/数据安全/核心来源绑定未见明确阻断性源码缺陷；冻结 hash 全部一致。
- MEDIUM：Ruff/Pyright/测试 PASS；业务全面语义以定向与完整 backtest unit suite 证实，不等价于真实八窗验收。
- **P1 证据问题**：成功退出证明缺失。触发路径：独立接收者按 v12 成品审查时，声明的 stdout/stderr 日志路径不存在，无法证实 2,040.9 秒任务正常退出，只能依赖交付 JSON 的二手陈述。建议补齐原 tmux pane 退出状态/原始 stdout、stderr 和命令身份的只读副本，并与 manifest SHA 绑定；不要重跑覆盖现有准备目录。
- 未确认其它 P0/P1 源码缺陷。八窗正式绩效未运行（遵守任务限制）；此报告不批准其绩效结论。
