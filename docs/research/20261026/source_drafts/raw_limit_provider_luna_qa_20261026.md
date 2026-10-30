# Raw limit provider 独立只读 QA

## 范围与冻结
- 仅审 `backtest/cnn_adapter/raw_market_provider.py` 与 `tests/unit/backtest/test_raw_market_provider.py`。
- 首末 SHA256 相同：provider `6604CB091E753C2ACFA6457F2463CF61DEEE4E7077F16A02DEE532A107E1A484`；tests `E388165C11639E4A812A5F481E27A5F2BCE6A43A14D8924D67D075A91950A031`。冻结确认 PASS。
- 两份 DeepSeek 报告均存在：`raw_limit_provider_delivery_20261026.md`、`raw_limit_provider_qa_20261026.md`。

## 行为审查
- PASS：provider:90-92 从 verified state 取上下界，单纯转 float 后传入 MarketBar；没有根据 ST/前收盘推算。缺键经 `state.get` 得 None，helper:19-20 保留 None。
- PASS：known 与价格来源独立。provider:78、87 按 `limit_known is True` 产生 `limit_state_known`；测试:158-168 验证价格存在、known=false 时仍 false。
- PASS：无效值 fail closed。helper:21-24 拒绝 bool/非数值；负值、NaN、上下界反序交由 MarketBar 校验；测试:181-211 覆盖对应拒绝。
- 核心覆盖行：测试:139-179（缺失、直传、known 独立、单界缺失）。

## RED 与 DeepSeek QA 报告核验
- `git show HEAD:tests/unit/backtest/test_raw_market_provider.py` 显示旧测试仅有 5 个测试；旧 `_provider` 辅助方法及新增绝对限价类均不存在。`git show HEAD:backtest/cnn_adapter/raw_market_provider.py` 显示旧 provider 未传绝对限价字段。
- 交付报告 RED 数字在逻辑上相符：8 个新增测试中 absent-key 测试应 PASS，其余 7 个因旧 provider 不传值/不触发校验而 FAIL。交付报告:35-45 的 1 PASS + 7 FAIL 枚举完整，DeepSeek QA 报告:25-31 指称该记录自相矛盾不成立。未在此重跑 RED 隔离脚本。
- DeepSeek QA 报告:79-88 声称测试:133 的 Pyright 错误是既有问题，与 `git show HEAD` 对照不符：旧文件没有此辅助函数或类型注解；该行来自新增测试代码，故不能称原有。

## 实际执行检查
- `uv run --project . --no-sync python -m unittest tests.unit.backtest.test_raw_market_provider`：Ran 13 tests，OK。
- `uv run --project . --no-sync ruff check backtest/cnn_adapter/raw_market_provider.py tests/unit/backtest/test_raw_market_provider.py`：All checks passed。
- `uv run --project . --no-sync pyright backtest/cnn_adapter/raw_market_provider.py tests/unit/backtest/test_raw_market_provider.py`：0 errors, 0 warnings, 0 informations。
- 上述 `--no-sync` 命令只读复用现有项目环境；未同步依赖。检查运行通过。

## 判定
**实现与检查 PASS。** 直传、None 保留、known 独立、无效值拒绝和 13 项测试均通过。DeepSeek QA 报告的 RED 矛盾判断及“Pyright 错误为原有”归因不通过，交付报告对 RED 的 1 PASS/7 FAIL 记录则与旧版源码及新测试相符。期间曾有两条命令因误用不含 worktree 的目录而失败，随后在指定 worktree 用上述命令成功；无文件改动（本 QA 报告除外）。
