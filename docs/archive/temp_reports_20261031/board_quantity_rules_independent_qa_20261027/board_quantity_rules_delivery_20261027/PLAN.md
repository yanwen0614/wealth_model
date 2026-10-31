# 独立质量门计划

- 范围：仅审查冻结的4个源文件及其接入；所有源码读取根为 `C:/Users/yanwen/.local/share/opencode/worktree/a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1/board-quantity-rules-20261027`。
- 冻结门：审查前后 SHA256 必须与 Generator 提供值一致；漂移即停止并判冻结版不通过。
- 证据：核对 SSE 2019 科创板第二十条、SSE 2020 主板规则3.4.7/3.4.9/3.4.11及暂缓条款；运行 RED/GREEN 探针、backtest 全量 unittest、Ruff、指定解释器 Pyright。
- 七关：范围、复用、契约、财务状态、错误拒绝、可验证性、兼容性。
- 写入范围：仅 `C:/Users/yanwen/AppData/Local/Temp/opencode/board_quantity_rules_independent_qa_20261027/board_quantity_rules_delivery_20261027/`。
- 约束：只读审查；不修改项目源码、测试、环境、锁文件，不执行提交或推送。
