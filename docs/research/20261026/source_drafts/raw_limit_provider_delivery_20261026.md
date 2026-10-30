# raw_limit_provider_delivery_20261026

## 任务范围
`backtest/cnn_adapter/raw_market_provider.py` 将 `verified_states` 中的
`absolute_limit_up_price` / `absolute_limit_down_price` 直接透传至 core `MarketBar`，
缺失为 None，不根据 ST/前收盘/4.5% 重建；`known` 标志严格原样。

## 前置: 同步 core wheel schema1.3
- 主区 wheel: `D:\code\cnn_full_20260905\cnn\wheels\backtest_core-0.1.0-py3-none-any.whl`
  SHA256: `76cc80e5fa8fa39513a21876137a5e1c99e001b7c74801a78b76345554d72470`
- 复制到 worktree wheels/ + uv.lock hash 更新
- `uv sync --offline` 成功

## 改动的业务文件

| 文件 | SHA256 |
|------|--------|
| `backtest/cnn_adapter/raw_market_provider.py` | `6604cb091e753c2acfa6457f2463cf61deee4e7077f16a02dee532a107e1a484` |
| `tests/unit/backtest/test_raw_market_provider.py` | `e388165c11639e4a812a5f481e27a5f2bce6a43a14d8924d67d075a91950a031` |

### raw_market_provider.py 变更（+24 行）
- 新增 `_to_float_price()`: `object → float | None`，None 透传 None，
  bool/非数值显式 ValueError
- `get_bar()` 新增两行：`absolute_limit_up_price`/`absolute_limit_down_price`
  经 `_to_float_price` 传入 `MarketBar`；core 负责正有限/大小顺序校验

### test_raw_market_provider.py 变更（+107 行）
- 新增 `RawMarketProviderAbsoluteLimitTest` 含 8 项测试；`_provider` 使用
  `Mapping[str, object] | None` + `Mapping[tuple[str, date], Mapping[str, object]]` 显式注解

## RED 阶段（旧 provider schema1.3 + 新测试，独立脚本验证）

```powershell
# 独立脚本：git show HEAD 旧源码 → exec 临时模块 → 替换引用 → 运行 8 新测试
# Ran 8 tests — FAILED (failures=7)
```
1 PASS + 7 FAIL：
- **`test_absent_keys_yield_none`** → **PASS**（旧 MarketBar 默认 None）
- `test_direct_passthrough` → FAIL（None != 11.0，旧代码未透传绝对限价）
- `test_known_flag_not_forced_by_price` → FAIL（None != 11.0）
- `test_single_boundary_missing` → FAIL（None != 11.0）
- `test_bool_rejected` → FAIL（ValueError not raised，旧代码未接入绝对限价字段）
- `test_negative_rejected` → FAIL（ValueError not raised）
- `test_nan_rejected` → FAIL（ValueError not raised）
- `test_reversed_order_rejected` → FAIL（ValueError not raised）

## GREEN 阶段（实现后）

```powershell
uv run --project . -m unittest tests.unit.backtest.test_raw_market_provider
# Ran 13 tests in 0.182s — OK
```
5 项原有 + 8 项新增 = 13/13 PASS

## 静态检查

| 工具 | 结果 |
|------|------|
| ruff check | All checks passed |
| compileall | 无错误 |
| pyright (两文件) | 0 errors, 0 warnings, 0 informations |

## git diff 范围（业务文件）

```
backtest/cnn_adapter/raw_market_provider.py     |  24 ++++++++++++++++
tests/unit/backtest/test_raw_market_provider.py | 107 +++++++++++++++++++++++++++++++++
```

## 测试清单

| 测试 | 场景 | 拒绝层 |
|------|------|--------|
| `test_absent_keys_yield_none` | 无 absolute_limit 键 → 字段为 None | — |
| `test_direct_passthrough` | 明确价格原样传递 | — |
| `test_known_flag_not_forced_by_price` | limit_known=False 不因有价变 True | — |
| `test_single_boundary_missing` | 只有 up，down 为 None | — |
| `test_bool_rejected` | bool 被 adapter `_to_float_price` 拒绝 | adapter |
| `test_negative_rejected` | 负值被 core MarketBar 拒绝 | core |
| `test_nan_rejected` | NaN 被 core MarketBar 拒绝 | core |
| `test_reversed_order_rejected` | down > up 被 core MarketBar 拒绝 | core |
