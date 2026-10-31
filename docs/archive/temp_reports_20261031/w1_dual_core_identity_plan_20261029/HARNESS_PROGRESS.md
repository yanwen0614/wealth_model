# 调试与交付进度

## 已完成（只读）

- [x] 阅读 systematic-debugging skill；遵守先取证、后提出方案，未编码或测试运行。
- [x] 阅读真实 prefix REPORT、三条 branch traceback、失败 JSON、CLI 顶层日志、hash 清单及 run_prefixes.ps1。
- [x] 阅读 fix5 报告/RUN_LOG 与 reverify4 报告/RUN_LOG；确认 94 项是合成/mini 门，不等于真实 W1 可执行性。
- [x] 阅读隔离 CNN `staged_production_inputs.py` 的准备、manifest 校验和 CLI 调用路径。
- [x] 只读比较安装 wheel 与隔离 core `account_runner.py`：隔离版增加 `stop_after_close` 校验/循环 break、待处理订单 provenance；API 不兼容于原 wheel。
- [x] 核对真实错误路径：三分支均在 `_verify_prepared` 比对实际 import 文件 SHA 时退出，未进入 `_load_prepared_window`。
- [x] 检查 tmux 声明：脚本正文无 tmux；报告无 pane 退出码/状态文件证据。故“是否实际在 tmux”无法确认，报告的肯定陈述证据不足。
- [x] 写出 PLAN、REVIEW_CHECKLIST、本进度和 ROOT_CAUSE_EVIDENCE；仅目标 Temp 目录为写入目的地。

## 已证实的 core 接口差异

- 安装 wheel 函数签名没有 `stop_after_close`；隔离版新增可选参数，验证 stop 日期属于 execution calendar 且等于 metric end，并要求 T+1 open。
- 隔离版在指定日 close snapshot 后 break；将 `stop_after_close` 与 pending orders 放进 provenance，并按 metric_end 截取指标计算。
- 原 wheel 不能直接执行 fix5 cutoff 参数；隔离 core 是真实前缀所需运行时，但不是 v12 准备 manifest 所记录的原 core。

## 尚未执行 / 交接边界

- [ ] 未修改任何源码、manifest、pin、wheel、baseline 或现有会话产物。
- [ ] 未运行测试、真实 prefix、全窗或任何绩效；未安装依赖。
- [ ] 未证明两 core 的真实逐事件 prefix 等价；提出的测试与运行仍属后续计划。
- [ ] 三份原始 branch 失败证据应完整保留；将来实验须使用全新输出根，失败即停止并保留八分支状态。
