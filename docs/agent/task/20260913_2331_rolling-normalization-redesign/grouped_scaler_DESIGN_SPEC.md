# quant-model 项目 - 归一化层（grouped_scaler）设计规格与方案（兼容 cnn-harness）

> Module: `grouped_scaler` | Version: v1.0 | Date: 2026-09-13 | Scope: `data/scaler.py` + `data/rolling_scaler.py` + `data/schema.py` + `data/dataset.py` 接入；`models/*` 仅消费 `featurenum`
> 输入依据：`grouped_scaler_MODULE_DESIGN.md`（Phase 1）+ `grouped_scaler_INTERVIEW_LOG.md`（Phase 3，Q1–Q7）
> 图规范：本文件所有架构/流程图为 ASCII 框线图。

# Part I: 设计规格与约束

## 0. 术语约定

| 关键词 | 含义 |
|--------|------|
| MUST | 强制 |
| MUST NOT | 强制禁止 |
| SHOULD | 推荐 |

## 1. 背景与动机

- 现状：默认 `F=69` = 51 raw feature + 18 个 G9 observation mask；`normalize ∈ {per_code, rolling}`，`rolling_scope ∈ {e2,e3,e4}`；`train.py:90` 硬断言 `featurenum==69`。
- 问题（Phase 1 §8）：
  1. G9 `*_raw`/`*_ts` 被 `clip[0,1]` 无差别截断，负值与量纲信息不可逆丢失；
  2. 18 个 G9 mask 有效秩≈1.05（97.09% 行完全相同、12 个可由 `value>0` 100% 推出），是 18 份冗余；
  3. rolling 对入 scope 的 G9 列短路 mask，`output_feature_cols` 与实际列数不一致（E5 会致命）；
  4. `close` 被禁入特征；
  5. `featurenum` 硬编码，F 任何变化即卡死；
  6. per_code 无子集入口，静态/动态归一化无法逐级对照。
- 动机：E1–E4（per_code vs rolling e2/e3/e4）在 warmup 修复后四臂 TopN 回测全部跑输基准，需以更干净的列分组与逐级对照矩阵重新检验归一化策略。

## 2. 核心设计理念（模型无关、pluggable、可配置）

- **列语义分组驱动**：先按金融语义把特征分为 P（价格量纲）/ R（无界比值）/ N（已归一化）/ G（G9 原始比值），每组绑定一种确定性变换规则；组与规则集中注册（Registry），不散落 `if/else`。
- **静态 / 动态正交**：`normalize`（模式）与 `feature_cols`/`scope`（列子集）是两个正交维度，任意组合。
- **逐级对照**：E0–E5 通过"P 组统计量从无→静态→动态、滚动列集从 P 逐级扩到 R 子集与 G9 raw"实现单变量递进。
- **模型无关**：`data/*` 不依赖具体 `models/*`；模型输入维度完全由数据层实测派生。
- **自描述产物**：checkpoint/`config.json` 必含 `feature_cols` 列名，评估/推理不依赖隐式列序假设。

## 3. 模块约束（MUST/MUST NOT）

### 3.1 依赖约束
- MUST 通过 `data/parquet_dataset`（即 `ParquetDataset`）加载数据，禁止在归一化层直读 parquet。
- MUST NOT 在 `data/*` 中 import 任何具体 `models/*`；归一化层与模型仅通过 `featurenum` 数值契约耦合。
- MUST NOT 在 `data` 层硬编码 `hidden_dim`/`num_layers`/`num_classes` 等模型超参；`featurenum` 由运行时实测派生。
- MUST 保持 scaler 生命周期：训练集 `fit`、验证/评估**复用**训练 state，禁止在验证/评估重拟合。

### 3.2 接口约束
- MUST 保持 `ParquetDataset.__getitem__` 返回 `(x, y, y_ret)` 元组契约；`x` 为 `[F_out, seq_len] float32`。
- MUST 所有 `models/*` 保持统一前向契约 `def forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]`（本项目双头实现另返 `ret_pred`，须经 `ModelConfig` 注入）。
- MUST `F_out == config.featurenum`，且 `featurenum` 的唯一事实源为运行时 `train_dataset.num_features`（= `scaler.feature_cols_out` 长度）。
- MUST 提供 `--featurenum` 可选入参：缺省 `None` 时自动推导，显式传值时与实测不一致 MUST 报错。
- MUST 训练导出/保存 config（`config.json`）时写入 `feature_cols` 列名（含 mask 列），保证 checkpoint 自描述。
- MUST 保持 `normalize` 三模式（`relative|per_code|rolling`）+ `none` 可选；`rolling_scope` 覆盖 `e0..e5`。

### 3.3 编码约束
- MUST 将列分组与变换规则集中注册在 `data/schema.py`（分组常量）与 `data/scaler.py`（`ColumnRule` 注册表），禁止在 `transform_code` 内散落按列名硬编码分支。
- MUST NOT 使用魔法数字：`asinh` 的 `scale`（amihud `1e12`）、`clip` 边界、`winsor` 百分位、`window/min_periods` 等 MUST 作为命名常量或 `ColumnRule` 字段。
- MUST 为 `*_raw`/`*_ts` 明确变换语义；MUST NOT 再对任何 G9 列使用无差别 `clip[0,1]`（仅 N 组 rank/ts 允许 `clip[0,1]`）。
- MUST 删除 `train.py:90` 的 `featurenum==69` 断言与 rolling 维度硬失败，改为"实测派生 + 记录/校验"。

### 3.4 性能约束
- SHOULD 支持 `num_workers>0` 与批量预取；rolling `_rolling_column` 已向量化，MUST 保持向量化不退化。
- MUST bump `CACHE_FORMAT_VERSION`、`SCALER_VERSION`、rolling payload version，使旧语义缓存/scaler 自动失效。
- SHOULD 使 `transform_config_digest` 仅纳入实际参与的特征组与 scope 子集，避免无关变更导致全量缓存失效。

# Part II: 详细设计方案

## 9. 整体架构（ASCII 框线图，体现 pluggable 注册）

```
                         ┌──────────────────────────────────────────────────────────┐
                         │ train.py CLI / config/defaults.py                         │
                         │  --normalize {relative,per_code,rolling,none}              │
                         │  --rolling_scope {e0..e5}   --feature_cols <list|preset>   │
                         │  --featurenum <int|None>（缺省推导）                        │
                         └───────────────┬──────────────────────────────────────────┘
                                         │ ParquetDataConfig
                                         ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ data/schema.py  ——  分组 & 白/黑名单 Registry                                    │
   │  FEATURE_GROUPS: {P:18, R:16, N:12, G:6}   APPROVED_RAW_FEATURES: 52             │
   │  G9_OBSERVATION_SOURCE = OR(18 G9 列 finite)   G9_MASK_COLUMNS = ("g9_observed",) │
   │  PROHIBITED_COLUMNS（移除 close）                                                 │
   └───────────────┬─────────────────────────────────────────────────────────────────┘
                   │ feature_cols
                   ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ data/scaler.py  ——  ColumnRule Registry（按组绑定变换）                           │
   │  ColumnRule(group, transform, clip, robust, winsor, scale)                        │
   │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐             │
   │  │ P: relative  │ │ R: asinh+clip│ │ N: clip01    │ │ G: fixed clip│             │
   │  │ clip±5       │ │ (±5, amihud  │ │ (G9 rank/ts) │ │ (E0–E4)      │             │
   │  │              │ │  ×1e12)      │ │              │ │ →E5 rolling  │             │
   │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘             │
   │         └────────────────┴────────────────┴────────────────┘                     │
   │                          ▼                                                        │
   │            Strategy 实现（pluggable，同一 transform_code 契约）                    │
   │   ┌────────────────┐ ┌────────────────────┐ ┌────────────────────────────┐        │
   │   │RelativeScaler  │ │PerCodeGroupedScaler│ │RollingNormalizer(+fallback)│        │
   │   │（E0，无 fit）  │ │（E1，静态 fit）    │ │（E2–E5，因果滚动）          │        │
   │   └────────────────┘ └────────────────────┘ └────────────────────────────┘        │
   │   scope 预设： e0=∅  e1=P  e2=P  e3=P+vol  e4=+vol/vol_ratio/amihud  e5=+G9raw   │
   └───────────────┬─────────────────────────────────────────────────────────────────┘
                   │ [N, F_out=53] （52 raw + 1 shared mask）
                   ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ data/dataset.py  ParquetDataset                                                  │
   │  warmup context（<start 作输入、不作标签日）→ 窗口[T=60] → 标签[52类]              │
   │  num_features = scaler.feature_cols_out 长度（单一事实源）                        │
   └───────────────┬─────────────────────────────────────────────────────────────────┘
                   │ 归一化后 features（memmap 缓存，key 含 identity）
                   ▼
   ┌─────────────────────────────────────────────────────────────────────────────────┐
   │ ModelRegistry / factory  ──▶  models/* pluggable                                  │
   │   ┌───────────────────────┐   forward(x:[B,F,T]) → [B,num_classes]（+ret_pred）   │
   │   │ cnn_transformer       │   stem Conv1d(F→128)+BN1d → Inception → Transformer  │
   │   └───────────────────────┘                                                        │
   │   ┌────────────┐ ┌────────────────┐ ┌────────────┐  （预留：LSTM/attention 等）    │
   │   │ (其它模型) │ │ (其它模型)     │ │ (其它模型) │                                  │
   │   └────────────┘ └────────────────┘ └────────────┘                                 │
   └───────────────┬─────────────────────────────────────────────────────────────────┘
                   ▼
            Trainer + Criterion(EMD/Huber)  →  checkpoint + config.json（含 feature_cols）
```

### 9.1 列分组与规则（Registry 内容）

| 组 | 列数 | 列 | 变换 | clip | 备注 |
|---|---|---|---|---|---|
| **P** | 18 | open,high,low,**close**,ma_5/10/20/60,ema_12/26,sar,trend_duokong,trend_shortline,macd,std_5/10/20,atr | `x/close[t-1]-1` + robust | ±5 | E0 无统计量；E1 静态；E2+ 滚动 |
| **R** | 16 | dmi,adx,boll,kelch,trend_duokong_dev,volatility_5/10/20,volume_ratio_5/10,gross_margin,net_margin,roe,roa,debt_to_equity,amihud | `asinh(x·scale)` | ±5 | amihud `scale=1e12`，其余 `scale=1` |
| **N** | 12 | G9 rank 6 + `*_ts` 6 | 恒等 | [0,1] | 保持现状 |
| **G** | 6 | G9 `*_raw` 6 | E0–E4 固定区间 clip；E5 滚动 winsor | 见表下 | 见 §11.3 |
| **mask** | 1 | `g9_observed` = OR(18 列 finite) | — | {0,1} | 追加在 52 raw 之后 |

- G9 `*_raw` E0–E4 粗 clip：`margin_net_buy_ratio_raw∈[-1,1]`、`margin_balance_chg_5d_raw∈[-1,5]`、`margin_buy_ratio_raw∈[0,1.5]`、`margin_balance_ratio_raw∈[0,1]`、`short_balance_ratio_raw∈[0,1]`、`short_sell_vol_ratio_raw∈[0,1]`；缺失填 0。

## 10. 核心接口契约（签名+类型+文档）

> **约束**：仅类定义、方法签名、类型注解、docstring；**不含方法体实现**（占位一律 `...`）。实现细节留给 quant-model（cnn-harness）Phase 2 Generator。

### 10.1 `data/schema.py`（分组与白/黑名单）

```python
from typing import Mapping

# 分组注册表：组名 -> 有序特征列名（顺序即输出顺序契约）
FEATURE_GROUPS: Mapping[str, tuple[str, ...]]  # {"P": (18,), "R": (16,), "N": (12,), "G": (6,)}

APPROVED_RAW_FEATURES: tuple[str, ...]  # 52 = P+R+N+G 拼接
G9_RAW_FEATURES: tuple[str, ...]        # 18 = rank 6 + raw 6 + ts 6（仍用于缺失/语义）
G9_OBSERVATION_SOURCE: tuple[str, ...]  # 18 列，OR 合成 shared mask
G9_MASK_COLUMNS: tuple[str, ...]        # ("g9_observed_mask",) 长度 1
PROHIBITED_COLUMNS: frozenset[str]      # 不再包含 "close"

def default_feature_cols(normalize: str) -> list[str]:
    """返回指定模式下的默认特征列（全新 schema，MUST 与 FEATURE_GROUPS 一致）。"""

def column_group(column: str) -> str:
    """返回列所属组名（"P"/"R"/"N"/"G"），未知列 MUST 报错而非静默透传。"""

def g9_observed_mask(frame: "pandas.DataFrame") -> "numpy.ndarray":
    """按 OR(任一 G9 列 finite) 计算共享 mask，shape [N]，dtype float32 ∈ {0,1}。"""
```

### 10.2 `data/scaler.py`（规则注册 + 静态/相对策略）

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class ColumnRule:
    """单列变换规则（Registry 的值；禁止在 transform 内按列名硬编码）。"""
    group: str
    transform: Literal["relative", "asinh", "passthrough", "clip01", "fixed_clip"]
    clip: tuple[float, float] | None
    robust: bool = False
    winsor: tuple[float, float] | None = None
    scale: float = 1.0
    relative_denominator: str | None = None  # P 组恒为 "close"

COLUMN_RULES: Mapping[str, ColumnRule]  # 列名 -> 规则

class RelativeScaler:
    """E0 策略：P 组 x/close[t-1]-1（clip±5），R/N/G 按 COLUMN_RULES，无 fit。"""
    feature_cols: list[str]
    feature_cols_out: list[str]
    mask_cols: list[str]

    def transform_code(self, code: str, features: "numpy.ndarray",
                      feature_cols: list[str], close: "numpy.ndarray | None" = ...) -> "numpy.ndarray":
        """返回 [N, F_out]；缺失填 0；mask 追加在末尾。"""

class PerCodeGroupedScaler:
    """静态 per-code 策略（E1）；支持按 feature_cols 子集收窄（仅 P 组）。"""
    def fit(self, frame: "pandas.DataFrame", feature_cols: list[str] | None = ...) -> "PerCodeGroupedScaler": ...
    def transform_code(self, code: str, features: "numpy.ndarray",
                      feature_cols: list[str], close: "numpy.ndarray | None" = ...) -> "numpy.ndarray": ...
    def validate_requested_schema(self, feature_cols: list[str], add_mask: bool = ...) -> None: ...
```

### 10.3 `data/rolling_scaler.py`（动态策略，scope e0–e5）

```python
from dataclasses import dataclass
from typing import Literal

RollingScope = Literal["e0", "e1", "e2", "e3", "e4", "e5"]

ROLLING_SCOPE_FEATURES: Mapping[str, tuple[str, ...]]  # 见 §13；e0=∅, e1=P, e2=P, e3=P+vol, e4=+vol_ratio/amihud, e5=+G9raw

@dataclass(frozen=True)
class RollingNormalizationConfig:
    window: int = 252
    min_periods: int = 120
    include_current_t: bool = True
    lower_percentile: float = 1.0
    upper_percentile: float = 99.0
    robust_clip: float = 5.0
    add_g9_masks: bool = True
    scope: RollingScope = "e5"

    def scope_features(self) -> tuple[str, ...]:
        """返回当前 scope 的滚动列集合（不含 mask）。"""

class RollingNormalizer:
    def output_feature_cols(self, feature_cols: list[str]) -> list[str]:
        """MUST 与实际 transform 产出的列数严格一致（含 1 个 shared mask）。"""

    def transform_code(self, features: "numpy.ndarray", feature_cols: list[str],
                      close: "numpy.ndarray", frozen_fallback: "numpy.ndarray | None" = ...) -> "numpy.ndarray":
        """返回 [N, F_out]；入 scope 的 G9 列 MUST 仍输出 shared mask，且不得短路。"""
```

### 10.4 `data/dataset.py` / `train.py` 接入

```python
@dataclass
class ParquetDataConfig:
    normalize: str = "per_code"       # {"relative","per_code","rolling","none"}
    rolling_scope: str = "e5"         # {"e0".."e5"}
    feature_cols: list[str] | None = None
    per_code_add_mask: bool = True
    # 其余既有字段保持不变

class ParquetDataset:
    @property
    def num_features(self) -> int:
        """F_out 的唯一事实源 = len(scaler.feature_cols_out)。"""

def configure_preprocessing(normalize: str, rolling_scope: str) -> dict:
    """按 mode/scope 隔离 SCALER_PATH/LOG_DIR；新增 relative 分支。"""

def build_preprocessing_metadata(mode: str, preprocessing_state, feature_cols: list[str],
                                 featurenum: int, seq_len: int, num_classes: int,
                                 scope: str | None = ..., seed: int | None = ...) -> dict:
    """MUST NOT 断言固定 69；MUST 断言 featurenum == 实测；MUST 落盘 feature_cols 列名。"""
```

## 11. 核心数据模型

### 11.1 张量契约
- Dataset 单样本：`x:[F_out, 60] float32`、`y:long(52)`、`y_ret:float32`（clip ±0.5）。
- DataLoader：`x:[B, F_out, 60]`；模型首层 `Conv1d(F_in→128,k=7)+BN1d`，`F_in == config.featurenum == F_out`。
- 标签：`future_ret[t]=open[t+1+horizon]/open[t+1]-1`，`horizon=5`；`BINS=linspace(-0.25,0.25,51)` → `C=52`。

### 11.2 F 组成（新默认 `F_out = 53`）
```
F_out = |P| + |R| + |N| + |G| + |mask| = 18 + 16 + 12 + 6 + 1 = 53
```
- 列顺序契约：`[P 18] → [R 16] → [N 12] → [G 6] → [g9_observed_mask]`。顺序 MUST 稳定并写入 `feature_cols_out`。
- 旧 `F=45`（39+6）与 `F=69`（51+18）均为历史 schema，本次全面替换，不再产出。

### 11.3 各组变换明细

| 组 | 输入域 | 变换 | 输出域 | 缺失处理 |
|---|---|---|---|---|
| P | 价格量纲 | `x/close[t-1]-1` →（E1/E2+）robust `(v-med)/(IQR/1.349)` → `clip(±5)` | ~N(0,1) 截断 | 填 0 |
| R | 无界比值 | `asinh(x·scale)` → `clip(±5)`；amihud `scale=1e12` | [-5,5] | 填 0 |
| N | G9 rank / ts | 恒等 → `clip(0,1)` | [0,1] | 填 0 |
| G | G9 `*_raw` | E0–E4：`clip(x, lo, hi)`（见 §9.1）；E5：rolling winsor(1,99) | 依列 | 填 0 |
| mask | — | `OR(18 G9 列 finite)` | {0,1} | — |

- P 组分母统一为 `close[t-1]`（`np.roll(close,1)`）；`close[t]/close[t-1]-1` 即 `return_1d`（已接受纳入）。
- E0 仅做 relative + `clip±5`（无 per-code 统计量），以保证 E0/E1/E2 对 P 组为"无/静态/动态"单变量对照。

### 11.4 共享 observation mask
- `g9_observed_mask = OR_{col∈G9}(isfinite(col))`，shape `[N]`，`float32∈{0,1}`。
- 语义："该股当期是否具备两融数据"；2.9% "部分有/部分无"行按 OR 归为 1。
- MUST 只输出 1 个 mask（删除旧 18 个逐列 mask）。
- E5 下即使 G9 `*_raw` 入滚动 scope，该 mask MUST 仍从原始 parquet finite 计算并输出。

### 11.5 rolling state / identity
- `_RollingDatasetState`：`normalizer`（config 含 scope `e0..e5`）+ `feature_cols` + `fallback_scaler` + `schema_manifest` + `identity_hash`。
- `fallback_scaler` 由训练集 fit 一次（per-code frozen），验证/评估复用，禁止重拟合。
- `identity/digest` payload MUST 纳入：`FEATURE_GROUPS`、`COLUMN_RULES`、scope 子集、`G9_MASK_COLUMNS`、`CACHE_FORMAT_VERSION`、`SCALER_VERSION`，并 bump 版本使旧缓存/scaler 失效。

## 12. 核心流程（ASCII 框线图）

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 1. CLI 装配  train.py                                                                    │
│    --normalize ∈ {relative,per_code,rolling,none}；--rolling_scope ∈ {e0..e5}            │
│    --feature_cols（可选子集）；--featurenum（可选，缺省推导）                              │
│    → configure_preprocessing：按 mode/scope 隔离 SCALER_PATH / LOG_DIR                   │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 2. 列选择  data/schema.py                                                               │
│    feature_cols = 显式子集 → 否则 default_feature_cols(normalize)                        │
│    分组：P18 / R16 / N12 / G6；校验禁止列（close 已解禁）                                 │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 3. 缓存 key（含 scaler identity）→ data/feature_cache.py                                 │
│    normalize + scope + feature_cols + digest + CACHE_FORMAT_VERSION 全参与               │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                       cache hit ───────┤
                     （校验 identity）   │ miss
                        ┌───────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 4. 读取 parquet → is_trading 过滤 → 时间过滤 + warmup context                            │
│    context = start 前 max(seq_len-1, 251/1) 行；标 _transform_context=True               │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 5. normalize 分支（Strategy）                                                            │
│    relative : RelativeScaler（无 fit）                                                   │
│    per_code : PerCodeGroupedScaler.fit(训练) / 复用(验证评估)                             │
│    rolling  : fit fallback(per-code) → RollingNormalizer(scope)                          │
│    none     : NaN→0 透传                                                                 │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 6. 逐 code transform（同一 transform_code 契约，按 COLUMN_RULES 分组）                     │
│    P/R/N/G → 各自变换；末尾追加 g9_observed_mask（1 列）                                   │
│    输出 [N, F_out=53]；NaN/inf → 0                                                        │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 7. 窗口 & 标签                                                                            │
│    label_pos = s + seq_len - 1；valid_starts: 非 context & future_ret 非 NaN             │
│    discrete = digitize(future_ret, BINS)                                                 │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 8. 写缓存（新 generation 原子发布）→ DataLoader → x[B,53,60]                              │
└───────────────────────────────────────┬─────────────────────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ 9. ModelRegistry 解析 ModelConfig(featurenum=53) → model.forward → (logits, ret_pred)    │
│    → Criterion → Trainer → checkpoint + config.json（含 feature_cols 列名）               │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## 13. 配置项设计

### 13.1 scope 预设（`ROLLING_SCOPE_FEATURES`）

| scope | 滚动列集 | 列数 | 用途 |
|---|---|---|---|
| `e0` | ∅（空集） | 0 | E0：P 仅 relative，无统计量 |
| `e1` | P | 18 | 名称占位；E1 走 `normalize=per_code`（静态，非滚动） |
| `e2` | P | 18 | E2：P 滚动 252 |
| `e3` | P + volatility_5/10/20 | 21 | E3 |
| `e4` | P + volatility + volume_ratio_5/10 + amihud | 24 | E4 |
| `e5` | e4 + G9 `*_raw` 6 | 30 | E5 |

> `e1` 与 `e2` 列集相同，语义区别在 `normalize`（`per_code` 静态 vs `rolling` 动态）；MUST 在 metadata 中区分记录 `mode` 与 `scope`。

### 13.2 实验臂映射（E0–E5）

| 臂 | `--normalize` | `--rolling_scope` | P 组统计量 | 滚动列 |
|---|---|---|---|---|
| E0 | `relative` | `e0` | 无 | 无 |
| E1 | `per_code` | `e1` | 全历史静态 robust | 无 |
| E2 | `rolling` | `e2` | 252 滚动 robust | P |
| E3 | `rolling` | `e3` | 252 滚动 robust | P + vol |
| E4 | `rolling` | `e4` | 252 滚动 robust | P + vol + vol_ratio + amihud |
| E5 | `rolling` | `e5` | 252 滚动 robust | e4 + G9 raw |

### 13.3 新增/变更配置项
- `ParquetDataConfig.normalize`：新增 `relative`。
- `ParquetDataConfig.rolling_scope` 默认由 `e4` 改为 `e5`。
- `config/defaults.py`：`featurenum` 占位按新 schema 调整为 53（仍会被实测覆盖）。
- CLI：`--feature_cols`（逗号/空格分隔或 preset）、`--featurenum`（缺省 None）。
- `CACHE_FORMAT_VERSION` / `SCALER_VERSION` / rolling payload version 全部 bump。

## 14. 测试策略

- **TDD，先测后码**。新增覆盖：
  - `data/schema.py`：`FEATURE_GROUPS` 计数（18/16/12/6）、`g9_observed_mask` OR 语义、`column_group` 未知列报错、`default_feature_cols` 顺序。
  - `data/scaler.py`：`ColumnRule` 路由；P relative+robust+clip；R `asinh`（amihud×1e12）；N clip01；G 固定区间 clip；E1 子集收窄只影响 P。
  - `data/rolling_scaler.py`：scope `e0..e5` 列集；入 scope 的 G9 列仍输出 shared mask 且列数等于 `output_feature_cols`；fallback 对齐断言。
  - `data/dataset.py`：`num_features==53`；`feature_cols` 子集；warmup context 不作标签日。
- **同步更新旧契约测试**：`test_data_schema_labels.py`、`test_rolling_normalization.py`、`test_data_feature_pipeline.py`、`test_eval_preprocessing.py`、`test_context_warmup_windows.py`、`test_config_defaults.py`、`test_train_metadata.py`。
- **验收命令**：
  ```bash
  uv run --project . python -m unittest discover tests/unit
  uv run ruff check .
  uv run --project . python train.py --smoke --num_workers 0 --rebuild_cache
  ```
- **端到端验收**：重建 scaler/缓存 → 全量重训 E0–E5（seed 42 / batch 1024 / patience 5）→ 截面 IC/xs_spread + TopN rolling 回测。

## 15. 迁移计划

1. **破坏性变更**：新 schema 全面替换，旧 `F=69`/18 mask/`per_code` 全量默认路径移除。
2. **产物作废**：旧 scaler `.pkl`、rolling state、memmap 缓存因版本 bump 自动失效；须 `--rebuild_cache` + 重拟合。
3. **文档同步**：`docs/per_code_normalization_spec.md`（G1~G9 决策）、`AGENTS.md`、`data/AGENTS.md` 的 F 描述更新为 53 与新分组。
4. **回滚**：以 git 分支 `feature/rolling-normalization-cnn` 为准；旧产物不兼容，回滚需切回旧 commit 并重建。
5. **落地顺序**：schema → scaler(ColumnRule/RelativeScaler) → rolling(scope/mask 修复) → dataset(relative 接入/featurenum) → train(CLI/metadata) → 测试 → 重建缓存 → E0–E5 重训。

# 附录

## 附录 A：违规检查清单

| # | 检查项 | 期望 |
|---|---|---|
| A1 | `data/*` 是否 import 具体 `models/*` | 否（仅 `featurenum` 数值契约） |
| A2 | 是否存在 `featurenum == 69` 之类固定断言 | 否（实测派生 + 可选校验） |
| A3 | 验证/评估是否重新 `fit` scaler | 否（复用训练 state） |
| A4 | G9 列是否仍被无差别 `clip[0,1]` | 否（仅 N 组 rank/ts 允许） |
| A5 | 是否仍输出 18 个逐列 mask | 否（仅 1 个 `g9_observed_mask`） |
| A6 | rolling 入 scope 的 G9 列是否短路 mask | 否（必须仍输出 shared mask，列数一致） |
| A7 | `close` 是否仍被禁入 `feature_cols` | 否（已解禁，进 P 组） |
| A8 | 变换是否按列名散落硬编码分支 | 否（`ColumnRule` Registry） |
| A9 | 是否存在未命名魔法数字（clip/winsor/scale/window） | 否（命名常量/`ColumnRule` 字段） |
| A10 | checkpoint 导出 config 是否含 `feature_cols` 列名 | 是 |
| A11 | 缓存/scaler 版本是否 bump 使旧语义失效 | 是 |
| A12 | `docs/per_code_normalization_spec.md` 与新 schema 是否一致 | 是 |

## 附录 B：变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-09-13 | 首版：7 题访谈定稿（Q5 重问后以"实测派生为权威 + 导出 config 写列名"定案） |







