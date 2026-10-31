# fix1 第二轮独立复验发现与处理

审查方 verdict：FAIL。其余门禁与静态/测试检查通过。

## 阻断发现
- `W1FractionalScenarioContext(period_id="W1-mini")` 可由外部直接构造；构造器未验证 synthetic market、mini signals 或 core 实际窗口，因此可绕开 staged runner 的 mini 限制。

## 已做修复
- 对公开构造器，只有真实 `period_id="W1"` 可走可信 prefix proof；其他 mini period 直接拒绝。
- 增加私有 bounded-mini factory，并在其中复验固定七日历、W1-mini config/source、单白名单事件、合成市场、信号文件 SHA、≤2MB、≤15行、≤5代码及固定三信号日。
- core mini context 超出固定结束日拒绝；直接公开构造 RED 用例修复后 GREEN。
- 非白名单事件验证期间强制严格税务失败关闭；税务状态恢复保持当前白名单 context 行为。

## 复验状态
- 93 项定向测试、Ruff、Pyright 均通过；原始 prefix proof SHA 仍未设置，未运行绩效。
- 当前改动已准备再次交同一只读审查会话；本文件不代表独立复验 PASS。
