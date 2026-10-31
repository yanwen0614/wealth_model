# 独立 QA 复核 1

日期：2026-10-28。承接 `../QA_REPORT.md`。仅复核原报告唯一 P1（v12 成功退出日志路径），未运行 prepare、未改源码/准备目录、未运行正式八窗绩效。未尝试恢复或声称持有 tmux pane。

## 结论

- **撤回原 P1，完整准备成功退出证据 PASS。** 上次是日志目录定位错误；原始文件实际位于 `staged_production_integration_delivery_20261027/`，不是 v12 输出目录。
- `run_v12.cmd`（SHA256 `692657afa0f128e2dcedfe9a45597e2ae21b78d7ae96d4aa2cc2459c1e02d609`）明确 `cd /d` 到工作树，调用指定主区解释器和 `--prepare-only`，将 stdout/stderr 重定向到该目录的 `prepare_v12.stdout.log`、`prepare_v12.stderr.log`，随后追加 `EXITCODE=%ERRORLEVEL%`。
- stdout 实读 4,426 行：尾部为 `DIAG: raw_cache 4424/4424 689009.SH`、`C:\Users\yanwen\AppData\Local\Temp\opencode\staged_prepared_inputs_20261027_v12\manifest.json`、`EXITCODE=0`。
- stderr 实读为 0 字节；SHA256 是空文件标准摘要。该证据来自磁盘原始日志，不依赖被销毁的 tmux pane。

## 日志与产物绑定

- stdout SHA256：`2995cb931fcf28c6d859ebb462ada43cac0d30cfb043bc7e2b3cb019f09c93b5`（162,689 字节）。stderr SHA256：`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`（0 字节）。
- stdout 末尾的绝对 manifest 路径与已检查目录一致。v12 `manifest.json` SHA256 `a8ad2b0bafebee235c9052eeba7a77db4404c6e0fbbbb40fe42457f3a8064441`，与 `manifest.sha256` 内容匹配。
- manifest `output_dir` 与 `raw_cache` 均指向该 v12 目录；`preparation_seconds=2040.8769080000347`，`artifacts` 4,812 项，逐项检查路径存在数为 4,812、缺失 0。实物 raw parquet 4,424 个、state shard 253 个。
- W1/W2 coverage、fees 摘要及其数值沿用主报告已核项目；没有重读 4GB 训练源，也没有重哈希全体原始市场源。外部日志身份通过脚本重定向、日志终端 manifest 路径、manifest 自身 SHA/sidecar、manifest 内输出目录和 artifact 存在性相互绑定。

## 冻结源码复核

- `SOURCE_HASHES_FINAL.json` 的 16 个冻结源码/测试文件再次复算：**16/16 匹配，0 变化**。工作树 HEAD 仍为 `ce7d1c6e0bd64136f10759412c55f6da410f128f`；工作树原有未提交整合文件状态保持不变。

## 结论边界

- 机械整合质量门：主报告记录的 378 backtest 测试通过（2 skip）、109 定向测试通过、Ruff 通过、Pyright 0 error/0 warning；本次复核仅解决准备成功退出证据缺口，不重跑验证。
- 准备交付证据：**PASS**（全量日志计数、脚本退出码、manifest/hash/output 绑定均核实）。
- `source_known=False`：仍为真实状态来源血缘尚未独立验收；不因本次退出证据而改变。
- `actual_after_tax_target_eligible=False`：仍为 false。税务/PIT/实施未知，实际税后目标资格未验收。
- 正式八窗回测绩效未运行、未验收。本报告不将完整 prepare-only 等同绩效结果或实际税后结论。
