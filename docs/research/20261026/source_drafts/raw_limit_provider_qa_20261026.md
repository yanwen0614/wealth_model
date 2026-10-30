# raw_limit_provider 独立只读 QA 报告

**审查者**: DeepSeek V4 Flash  
**日期**: 2026-10-26  
**工作树**: `staged-bridge-20261026` (freeze SHA provider `6604cb0`, tests `5841cdeb`)  
**核心**: `backtest_core-0.1.0` schema 1.3 (wheel SHA `76cc80e5`)

---

## 1. 工具结果汇总

| 检查项 | 结果 |
|--------|------|
| 13 项测试 (5 原有 + 8 新增) | **13/13 PASS** (0.205s) |
| Ruff | **All checks passed** |
| Pyright provider | **0 errors** |
| Pyright test 文件 | **1 error** (类型窄化，已有问题，非本次引入) |

---

## 2. RED 阶段描述自相矛盾

交付文档 `raw_limit_provider_delivery_20261026.md:34` 的 RED 阶段描述存在以下矛盾：

1. **计数矛盾**: RED 宣称 "FAILED (failures=7)" 且 "7 项新测试全失败"，但仅枚举了 5 项测试（`test_absent_keys_yield_none` + 4 项 rejected = 5）。GREEN 阶段又说 "5 项原有 + **8 项新增**"。7 ≠ 8。

2. **自身矛盾**: `test_absent_keys_yield_none` 的 RED 失败原因是 "None != 11.0 × 3"，但该测试代码（第 136-142 行）中没有 11.0，只有 `assertIsNone` 断言。11.0 来自 `test_direct_passthrough`（第 152 行），不在此测试中。

3. **absent test 应 PASS**: 在 only-provider-changed-not-implemented 状态下（即 verified_states 未传入 absolute_limit 键），MarketBar 字段默认值为 None，`test_absent_keys_yield_none` 的 `assertIsNone` 应 PASS。RED 描述说它失败，与默认 behavior 矛盾。

结论：**RED 计数和原因描述不可采信**。实际基线验证见第 3 节。

---

## 3. 四项目标审查

### 3.1 direct known界透传 — PASS

**机制**: `raw_market_provider.py:91-92` 调用 `_to_float_price` 将 `verified_states` 中的 `absolute_limit_up_price` / `absolute_limit_down_price` 直接转换为 `float | None`，无任何推导、重建或修改。核心验证链：

- `state.get("absolute_limit_up_price")` → `_to_float_price(v, "absolute_limit_up_price")` → `float(v)` → MarketBar
- MarketBar `__post_init__` 只做正有限/大小顺序校验，不改值

**行号**: provider:91-92  
**测试**: `test_direct_passthrough` (test:144-153) — 11.0/9.0 原样通过

### 3.2 unknown 不转 known — PASS

**机制**: `limit_state_known` 始终来源于 `verified_states` 的 `limit_known` 条目（provider:78），与 `absolute_limit_up_price`/`absolute_limit_down_price` 是否存在完全独立。价格字段不存在时 `limit_state_known` 仍可为 True；价格存在时也可为 False。

**行号**: provider:78,91-92  
**测试**: `test_known_flag_not_forced_by_price` (test:155-165) — `limit_known=False`，有价格 → `bar.limit_state_known` 仍为 False，价格透传不变

### 3.3 None/invalid fail closed — PASS

**None 路径**: `state.get("absolute_limit_up_price")` 缺键 → `_to_float_price(None, ...)` → None → MarketBar 字段 None。`MarketBar.__post_init__` 对 None 跳过校验。  
**bool 路径**: `_to_float_price` 第 21 行 `isinstance(value, bool)` → `raise ValueError`。注意 core 的 `ensure_finite`（`validation.py:41`）已有 `isinstance(value, bool)` 拒绝，provider 层双重防护可接受。  
**非数值路径**: `_to_float_price` 第 23 行 `not isinstance(value, (int, float))` → `raise ValueError`。  
**NaN 路径**: `float(float("nan"))` 通过 `_to_float_price` → MarketBar `ensure_finite` 检查 `math.isfinite` → `raise ValueError`。  
**负值路径**: `float(-1.0)` 通过 `_to_float_price` → MarketBar `__post_init__` 中 `if price <= 0: raise ValueError`。  
**反序路径**: 两值均通过 `_to_float_price` → MarketBar `if lower > upper: raise ValueError`。  
**string 路径**: `_to_float_price` 第 23 行 → `raise ValueError`。

**行号**: provider:19-25  
**测试**: `test_absent_keys_yield_none` (test:136-142), `test_single_boundary_missing` (test:167-176), `test_bool_rejected` (test:178-184), `test_negative_rejected` (test:186-192), `test_nan_rejected` (test:194-200), `test_reversed_order_rejected` (test:202-208)

### 3.4 边界情况：`_to_float_price` 与 core `ensure_finite` 的 bool 拒绝交集

`_to_float_price` 的 bool 检查（provider:21-22）在 **所有 int-子类场景** 覆盖 True/False，与 core `ensure_finite`（`validation.py:41`）行为一致，但有更早拦截的位置优势。对测试 `test_bool_rejected` 来说，即使移除 provider 层的 bool 检查，core 层也能拒绝，因此测试结果是正确的（只是文档说"core 明确拒绝"也无需纠正，两层都拒绝）。

注意：`_to_float_price` 缺失显式的 `int`→`float` 转换前 `nan/inf` 前缀检查。`float(float("nan"))` 成功通过，借 core 层兜底。这是设计选择而非缺陷。

---

## 4. Pyright 告警分析

### 4.1 原有测试文件告警（非本次引入）— 1 error

**位置**: `tests/unit/backtest/test_raw_market_provider.py:133`  
**类型**: `reportArgumentType`  
**描述**: `dict[tuple[Literal['A.SZ'], date], dict[Unknown, Unknown]]` 不可赋值给 `Mapping[tuple[str, date], Mapping[str, object]] | None`；`_KT@Mapping` 是不变类型参数，`Literal['A.SZ']` 不等同于 `str`。  
**根因**: `_provider` 方法签名 `state: dict | None` 无内部类型参数，推导为 `dict[Unknown, Unknown]`。  
**严重度**: 低（不影响运行时，类型窄化是已知 Python type system 局限）  
**是否本次引入**: 否（该签名问题从测试套件创建起即存在，8 项新增测试均复用此辅助方法）

### 4.2 本次无新增告警

两个业务文件的 Pyright 对比：provider 文件 0 errors；test 文件的 1 error 为原有结构性问题，非本次 99 行新增代码引入。

---

## 5. Ruff 告警分析

**结果**: All checks passed（零告警）

无新增或残留告警。

---

## 6. 最终判定

| 维度 | 判定 | 说明 |
|------|------|------|
| 直接透传 | **PASS** | verified_states 值经 `_to_float_price` 纯转换进入 MarketBar，无推导/重建 |
| known 不污染 | **PASS** | `limit_state_known` 与价格字段完全解耦，各自独立传递 |
| 无效值 fail closed | **PASS** | None 透传；bool/string/NaN/负/反序均已拒绝（provider 层或 core 层） |
| 测试覆盖 | **13/13 PASS** | 5 原有 + 8 新增全部通过 |
| 静态类型 | **PASS (with caveat)** | provider 零告警；test 文件 1 个已存在 Lint 级告警 |
| RED 描述 | **不可采信** | 计数矛盾 (7≠8)、失败原因与代码不符 (None≠11.0)、absent test 应 PASS 但记录为失败 |

---

## 7. 建议修复（不改代码，仅列举）

1. **`test_raw_market_provider.py:128`** `_provider` 签名改为 `state: Mapping[str, object] | None = None` 可消除 Pyright error 133。当前运行时正确，仅在严格类型检查中出现。

2. **`_to_float_price`** 对 `int(float("nan"))`/`int(float("inf"))` 无独立前检，core `ensure_finite` 会兜底拒绝。如需 provider 层统一错误信息风格可增加，当前非必改。
