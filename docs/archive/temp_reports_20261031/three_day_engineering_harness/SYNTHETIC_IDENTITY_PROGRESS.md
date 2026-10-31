# 逐分支运行身份模块进度

## 范围

- 仅新增 `backtest/cnn_adapter/run_identity.py` 与 `tests/unit/backtest/test_run_identity.py`。
- 未接入 runner/engine；没有读取或修改费用、终端实现、core 仓库、日期标签文件、既有审计脚本或既有测试。
- 所有身份来源为调用者传入的路径及当前 Python 进程实际已加载模块；测试使用临时合成源和产物。

## 实现

- `capture_run_identity` 记录 cnn/core 的 HEAD、branch、含未跟踪文件的 dirty 明细，模块/产物绝对路径、大小和 SHA-256，发行包与 Python 版本；每次采集生成 UUID `capture_id` 并纳入规范 JSON 身份哈希。
- 仓库路径必须等于 `git rev-parse --show-toplevel`，cnn/core 不得相同或相互嵌套；文件/path/stat 错误统一转为 ValueError，采集期文件与 Git 变化失败。
- `validate_branch_identities` 检查非空且唯一 capture_id、label 与必需证据；相同内容在独立 capture 下可通过，重复对象或复用 capture_id 失败。

## 验证

- RED：新回归测试分别捕获缺少 capture_id、仓库根目录未核验、stat 前置异常未转换为 ValueError。
- GREEN：`rtk uv run python -m unittest tests.unit.backtest.test_run_identity`：9 项通过。
- Lint：`uv run rtk ruff check backtest/cnn_adapter/run_identity.py tests/unit/backtest/test_run_identity.py`：通过。
- 未运行其他测试、真实数据、训练或 GPU 工作；未提交、推送或删除文件。

## 边界

- CNN 新模块与运行身份模块以正式模块名匹配；core 模块以已加载模块名后缀匹配，传入路径仍须等于加载模块的 `__file__`。
- 尚未验证真实候选运行身份、真实 core 导入布局、并发变更注入或生产数据产物；只记录路径、大小和哈希，不解析文件内容格式，这不是候选策略放行证据。
