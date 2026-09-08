---
description: 生成模型通用设计规格文档 - 扫描代码 + 交互式访谈 + 输出设计规格（quant-model 兼容 cnn-harness）
---

为 quant-model（兼容 cnn-harness）项目的任意模型或子模块，或某个（可能模糊、不明确的）需求，生成完整的模型通用设计规格文档套件。支持任意模型架构（`models/*`：`model2`, `cnn_lstm_attention`, `attention` 等）通过 pluggable 注册机制接入。

> 图规范：所有架构图 / 流程图使用 ASCII 框线图（如 `┌─────┐`、`│     │`、`└──┬──┘`、`──▶`），禁止使用 Mermaid。整体架构图必须体现 pluggable 模型注册机制。

## 执行步骤

### Phase 0: 解析需求（支持模糊/不明确需求）

从用户输入中提取自由形式的需求描述，不预先假设其已对应某个明确模块。

1. 提取原始需求文本（保留用户原话，暂不归类）。
2. 需求类型判断：
   - 明确型：可直接映射到模块（见下表）→ 解析目标模块。
   - 模糊型：仅描述目标 / 痛点 / 现象（如「K 线很慢」「loss 不收敛」）→ 不强行映射，进入探查与澄清。
3. 模糊需求处理：
   - 先派遣 explore 子代理对代码库做轻量扫描，定位可能相关的模块；
   - 与用户交互确认范围（每次 1 个问题，规则见 Phase 3）。
4. 明确型模块映射表（仅作参考，非唯一步骤；模型一律泛化为 `models/*`）：

| 语义输入 | 目标模块 |
|---------|---------|
| parquet / dataset / 数据加载 | `data/parquet_dataset` |
| scaler / 归一化 / per_code | `data/grouped_scaler` + `data/per_code_scaler` |
| model / CNN / Transformer / 任意模型架构 / model2 / attention | `models/*`（任意模型：`model2`, `cnn_lstm_attention`, `attention` … pluggable） |
| training / 训练链路 / Trainer | `training` |
| loss / 损失 / EMD | `criterion` |
| inference / 推理 / 预测 | `inference.py` |
| config / 配置 / yaml | `config` |
| 数据很慢 / K线很慢 | `data/parquet_dataset` |
| loss不收敛 / 训练不稳定 | `training` + `models/*` + `criterion` |

输出目录：`docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/`

> `{MODULE}` 为文档主体标识：明确型取其模块名（如 `parquet_dataset`），模糊型取其需求领域短标识（如 `kline-slow`）。

### Phase 0.5: 版本管理检查

1. glob 扫描 `docs/agent/task/*_{task-tag}/` 下是否已有同名文档
2. 如有 → 读取版本号，递增小版本，备份旧文件
3. 如无 → 从 v1.0 开始

### Phase 1: 模块代码分析（模型通用，扫描 `models/*`）

派遣 explore 子代理分析目标模块：
- 完整目录结构和文件布局
- 所有关键源文件内容（接口定义、核心类、数据模型）
- `__init__.py` 中导出的公共 API（模型注册表 / factory）
- 已有的 AGENTS.md 或其他文档
- 与其他模块的 import 依赖关系
- quant-model 通用扫描维度（兼容 cnn-harness，需覆盖任意模型）：
  - `models/*` 全量扫描（含 `model2`, `cnn_lstm_attention`, `attention` 等）及 pluggable 注册机制（`models/__init__.py` / `register_model` / factory）
  - 通用模型契约：`def forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]` + `ModelConfig(featurenum, seq_len, num_classes)`
  - 整体架构 ASCII 图必须体现 pluggable 模型注册（Config → Registry → 任意 Model → Trainer/Criterion）
  - 特征维度与时序窗口解耦（`featurenum`/`seq_len`/`num_classes` 由 config 注入，非硬编码）
  - 损失函数与优化器与模型解耦（criterion/EMD_loss、cross-entropy 可插拔）
  - 训练链路（`main_parquet.py` → DataLoader → `models/*` via registry → Trainer → log_manager）

生成 `{MODULE}_MODULE_DESIGN.md`：

```markdown
# quant-model 项目 - {模块显示名} 模块现状设计文档（兼容 cnn-harness）

> Module: `{module}` | Version: {current} | Date: {YYYY-MM-DD} | Scope: `models/*` pluggable

## 1. 模块概述
### 1.1 模块定位（在 pluggable 体系中的位置）
### 1.2 模块职责
### 1.3 模块边界（与 data/training/criterion/config 的契约）

## 2. 架构设计
### 2.1 整体架构（ASCII 框线图，必须含 Registry/Factory → models/* 分支）
### 2.2 核心设计模式（Registry / Strategy / Config 注入）

## 3. 文件清单
（表格：文件路径 | 类名 | 职责 | 行数，models/* 需逐模型列出）

## 4. 核心数据模型
（通用：`Tensor[B,F,T]` 输入、`Tensor[B,num_classes]` 输出；`featurenum`/`seq_len`/`num_classes` 来源于 config）

## 5. 核心类详解
### 5.x {ClassName}
- 职责
- 关键方法签名（含 `forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]`）
- 依赖关系（是否经 registry 创建）

## 6. 核心流程（ASCII 框线图）
（数据加载 → 归一化 → Registry 解析 ModelConfig → 模型前向 `forward` → 损失计算 → 反向传播）

## 7. 模块依赖关系（重点：data 不依赖具体 model，training 仅依赖 Registry 接口）

## 8. 已知问题与痛点

## 9. 演进方向建议（如何新增一个模型：实现 forward + 注册 + config）
```

### Phase 3: 交互式访谈

基于 Phase 1 文档，与用户进行交互式访谈：

**问答规则**：
1. 每次只问 1 个问题
2. 每个问题标注分类标签：`[工程]` / `[算法]` / `[工程+算法]`
3. 优先使用选择题
4. 问题基于 Phase 1 的代码分析

**问答维度**（模型通用，需覆盖 pluggable 与通用契约）：

| 维度 | 典型问题方向 |
|------|------------|
| 模块定位与边界 | 核心职责、与相邻模块的边界；`models/*` 与 data/training 的解耦 |
| 接口设计 | 公共 API、数据流转、Dataset 接口；`forward(x: Tensor[B,F,T]) -> Tensor[B,num_classes]` 契约 |
| 模型注册与扩展 | Registry/Factory 设计、如何新增 `models/*`（如 `cnn_lstm_attention`）、配置注入 |
| 性能与可靠性 | Parquet 批量加载、大数据量、num_workers；不同模型的前向开销 |
| 数据一致性 | 归一化分组、per-code 隔离、泄漏防护；`featurenum/seq_len` 一致性校验 |
| 扩展性 | 如何新增模型/损失/特征而不改动 data/training 核心 |
| 训练策略 | 损失收敛、类别不平衡、早停；模型无关的 criterion 适配 |
| 测试策略 | 测试层级、覆盖范围；针对 `models/*` 的契约测试（shape 断言） |

生成 `{MODULE}_INTERVIEW_LOG.md`。

### Phase 4: 生成设计规格文档（模型通用模板）

```markdown
# quant-model 项目 - {模块显示名} 设计规格与方案（兼容 cnn-harness）

> Module: `{module}` | Version: v{X.Y} | Date: {YYYY-MM-DD} | Scope: `models/*` pluggable

# Part I: 设计规格与约束

## 0. 术语约定
| 关键词 | 含义 |
|--------|------|
| MUST | 强制 |
| MUST NOT | 强制禁止 |
| SHOULD | 推荐 |

## 1. 背景与动机
## 2. 核心设计理念（模型无关、pluggable、可配置）
## 3. 模块约束（MUST/MUST NOT，模型通用）
### 3.1 依赖约束
- MUST 通过 `data/parquet_dataset.ParquetDataset` 加载数据，禁止直读 parquet
- MUST NOT 在 `data` 层硬编码任何模型超参（`num_classes`/`hidden_dim`/`num_layers`/`featurenum`/`seq_len` 等）
- MUST 通过 config 注入 `featurenum`/`seq_len`/`num_classes`，模型仅消费配置
### 3.2 接口约束
- MUST 保持 Dataset `__getitem__` 返回 (feature, label) 张量契约
- MUST NOT 在训练层绕过 `grouped_scaler` 直接归一化
- MUST 所有 `models/*` 实现统一前向契约 `def forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]`
- MUST 提供 `ModelConfig`（含 `featurenum`, `seq_len`, `num_classes`）并经 Registry/Factory 创建模型
### 3.3 编码约束
- MUST 使用 `config/*.yaml` 统一配置，禁止魔法数字；新增模型仅通过注册接入
- MUST NOT 在 `models/*` 外散落模型选择 `if/else` 分支，统一走 `register_model` / factory
### 3.4 性能约束
- SHOULD 支持 `num_workers>0` 与批量预取；前向需支持批量 `B` 维度

# Part II: 详细设计方案

## 9. 整体架构（ASCII 框线图，必须体现 pluggable 注册）
示例（按需调整，需保留 Registry 分支）：
```
┌─────────┐   ┌──────────────┐   ┌─────────────────────┐   ┌──────────┐
│ Config  │──▶│ ModelRegistry│──▶│ models/* pluggable  │──▶│ Trainer  │
│ yaml    │   │  factory     │   │ ┌─────┐ ┌─────────┐ │   │  +       │
└─────────┘   └──────────────┘   │ │model2│ │cnn_lstm │ │   │ criterion│
              ┌─────────┐        │ └─────┘ │_attention│ │   └──────────┘
              │  data   │───────▶│ ┌────────┐         │ │
              │Parquet  │        │ │attention│         │ │
              └─────────┘        │ └────────┘         │ │
                                 └─────────────────────┘ │
```
## 10. 核心接口契约（签名+类型+文档）

> **约束**：仅包含类定义、方法签名、类型注解、docstring。**严禁包含方法体实现**（`pass` 或 `...` 占位均不可）。实现细节完全留给 `quant-model`（兼容 `cnn-harness`）Phase 2 Generator 阶段。

通用模型契约示例（必须包含）：
```python
from dataclasses import dataclass
import torch
from torch import Tensor

@dataclass
class ModelConfig:
    """模型通用配置（由 config.yaml 注入，禁止在 data 层硬编码）。"""
    featurenum: int
    seq_len: int
    num_classes: int
    hidden_dim: int = 128
    dropout: float = 0.1
    ...

class BaseModel(torch.nn.Module):
    def __init__(self, config: ModelConfig) -> None:
        """经 Registry/Factory 创建，消费 ModelConfig。"""
        ...

    def forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]:
        """通用前向契约：B=batch, F=featurenum, T=seq_len → B×num_classes logits。"""
        ...

# 注册示例（pluggable 机制）
@register_model("my_model")
class MyModel(BaseModel):
    def forward(self, x: Tensor[B,F,T]) -> Tensor[B,num_classes]:
        """具体模型的前向实现占位（文档阶段仅签名）。"""
        ...
```
## 11. 核心数据模型
## 12. 核心流程（ASCII 框线图）
## 13. 配置项设计
## 14. 测试策略
## 15. 迁移计划（如有）

# 附录
## 附录 A：违规检查清单
## 附录 B：变更记录
```

## 交付件清单

| # | 文件名 | 说明 |
|---|--------|------|
| 1 | `{MODULE}_MODULE_DESIGN.md` | 当前模块代码分析文档 |
| 2 | `{MODULE}_INTERVIEW_LOG.md` | 访谈记录（设计决策） |
| 3 | `{MODULE}_DESIGN_SPEC.md` | 设计规格文档（MUST/SHOULD 约束 + 详细方案） |

## 自动提交（★必做）

任一交付件写入 `docs/agent/task/{tag}/` 后**立即自动提交**，避免文档悬空：

1. `git add docs/agent/task/{yyyyMMdd_HHmm}_{task-tag}/`
2. `git commit -m "docs: add spec for {MODULE} {task-tag}"`（worktree 提交到分支，主区提交到 main；`--no-push` 可跳过推送则仅本地提交）
3. `git push`（失败仅提示不阻塞）
4. 展示 `git log --oneline -1` 与 `git status`

> 分阶段产出时：ModuleDesign 完成后可先提交一次，访谈与 Spec 完成后各再提交一次；或一并在 DESIGN_SPEC 完成后统一提交。`merge-worktree --finish` 会 squash 为唯一 commit（worktree 场景）。

## Red Flags

| 错误行为 | 纠正方式 |
|----------|---------|
| 跳过 Phase 1 直接提问 | 必须先生成 MODULE_DESIGN |
| Phase 1 没写入文件就进入下一阶段 | 每个 Phase 必须写入交付件文件 |
| 一次问多个问题 | 回退，一次只问一个 |
| 没等用户确认就进入下一阶段 | 每个交付件必须用户确认 |
| DESIGN_SPEC 的 Part I 没用 MUST/MUST NOT | 必须使用约束风格 |
| 没检查已有文档版本就直接覆盖 | 必须先执行 Phase 0.5 |
