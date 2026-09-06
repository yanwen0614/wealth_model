# 审查清单 — pure-reg-loss-ablation

> 生成时间：2026-09-05 11:40

## 需求理解

新增"纯回归损失"消融实验分支 pure_reg，与 base（EMD 分类）/ dual（EMD+λ·Huber）构成三组对照：

1. criterion/pure_reg_loss.py（新建）：PureRegLoss(nn.Module)，is_dual_head=True 类属性，4 参签名 forward(logits, ret_pred=None, targets_cls=None, targets_ret=None) 对齐 DualLoss（criterion/dual_loss.py，43 行）；缺 ret_pred/targets_ret 时退化返回三元组 zeros；reshape(-1)、dtype/device 对齐参照 dual_loss.py:36-42；返回三元组 (total, reg_part, cls_zero)，total=reg_part=HuberLoss(ret_pred, targets_ret)；分类头 logits 不进损失（无梯度）。
2. train.py（modify）：CLI 加 --pure_reg（store_true）；config 加 'PURE_REG': False；criterion 选择（236-241 行）改三分支 PURE_REG 优先：if PURE_REG: PureRegLoss(num_classes, huber_delta=HUBER_DELTA) elif DUAL_HEAD: DualLoss else EMDLoss；日志打印 pure_reg 模式说明；config.json 由 LoggerManager 自动持久化（已确认 log_manager/__init__.py:65-70 _save_config 整体 json.dumps，PURE_REG 键会进 config.json）。
3. scripts/eval_bins_mapping.py（modify）：load_run_model_cfg（62-72 行）扩展读顶层键 PURE_REG；纯回归模式推理取 out[1]（ret_pred）作为 exp_ret（替代 softmax·CENTERS52，166 行）；RankIC/TopK/11/13 映射全用 ret_pred；分类头 52acc 照算但输出注明"分类头未训练（pure_reg 模式）"。
4. 验证：uv run --project . python train.py --max_codes 200 --epochs 1 --batch_size 512 --num_workers 0 --pure_reg 冒烟跑通 + 全市场截面 eval 兼容 pure_reg checkpoint。

### 显式假设（编码前确认，未阻断）

- A1: 模型层零改动（model.py:110,130 forward 恒返 (logits, ret_pred)，fc_reg 无条件构造）——已勘察采信。
- A2: Trainer._compute_loss（trainer.py:33-40）经 is_dual_head 判别走 4 参调用、tuple 返回取 result[0]，training/ 零改动。
- A3: 数据集 __getitem__ 返回 3 元 (x, y_cls, y_ret)，y_ret 已 clip ±0.5（dataset.py:380），data/ 零改动。
- A4: PURE_REG 优先于 DUAL_HEAD（if/elif 顺序），两者同开时按 pure_reg 执行，不报错。
- A5: 旧 checkpoint config.json 无 PURE_REG 键时 eval 默认 False，走原 softmax·CENTERS52 路径（向后兼容）。
- A6: 分类头不训练机制 = logits 无梯度（grad=None 参数 AdamW 自动跳过），不做 requires_grad=False 手工冻结。
- A7: 验证全程不得干扰 tmux 后台 full_base（run_20260905_025222）/ full_dual（run_20260905_025822）：GPU 峰值 2.4GB/8GB 有余量，CPU 8 核 ~50% 占用，验证一律 --num_workers 0 且串行。
- A8: 本任务不涉及数据/归一化链路（per_code、README_TRAINING_CHAIN.md、docs/per_code_normalization_spec.md 不受影响，仅确认不破坏）。
- A9: criterion/AGENTS.md"EMDLoss 唯一损失"表述约束的是既有主链路默认行为；新增 PureRegLoss 为独立消融分支，不改动 EMDLoss 及其默认实例化路径，符合"改损失保持与 Trainer 兼容签名"的实质约束。

## 影响范围

| 模块 | 文件 | 操作 | 说明 |
|------|------|------|------|
| criterion | criterion/pure_reg_loss.py | 新增 | PureRegLoss 纯回归损失（⚡full 触发层） |
| tests | tests/unit/criterion/test_criterion_pure_reg_loss.py | 新增 | TDD 数值行为单测 |
| 根入口 | train.py | 修改 | import/config/CLI/三分支/日志共 5 处小改 |
| scripts | scripts/eval_bins_mapping.py | 修改 | load_run_model_cfg 扩展 + ret_pred 收集 + exp_ret 分支 + 标注 |
| training | （零改动） | - | _compute_loss 已兼容 is_dual_head |
| models | （零改动） | - | forward 恒返 tuple |
| data | （零改动） | - | (x, y_cls, y_ret) 3 元已就绪 |
| log_manager | （零改动，仅确认） | - | _save_config 整体序列化 → PURE_REG 进 config.json |

## 重复检测

| 搜索关键词 | 是否存在 | 位置 | 结论 |
|------------|---------|------|------|
| PureRegLoss / pure_reg | 否 | criterion/ 仅 __init__.py、emd_loss.py、dual_loss.py | 无重复实现，需新建 |
| HuberLoss | 是 | criterion/dual_loss.py:29（内嵌子模块） | 复用 nn.HuberLoss 范式；不抽公共基类（独立类避免耦合 EMD 子模块） |
| is_dual_head | 是 | criterion/dual_loss.py:20 + training/trainer.py:35 | 判别机制现成，PureRegLoss 直接复用，Trainer 零改动 |
| DualLoss 4 参签名/对齐逻辑 | 是 | criterion/dual_loss.py:31-43 | 签名、reshape、dtype/device、退化逻辑逐行参照 |
| load_run_model_cfg | 是 | scripts/eval_bins_mapping.py:62-72（唯一调用点 118 行） | 唯一 config.json 读取点，扩展此函数而非新增 IO |
| softmax·CENTERS52 → exp_ret | 是 | scripts/eval_bins_mapping.py:166 | pure_reg 分支替换点，下游 167-233 零改动 |
| 旧 npz/inference 链路 | 否 | 已在 e69a47b 删除 | 无可参考废弃代码 |
| 既有测试参考 | 是 | tests/unit/criterion/test_criterion_dual_loss.py | unittest 风格、数值对照写法直接对齐 |

## 质量关卡

| # | 关卡 | 检查项 | 优先级 |
|---|------|--------|--------|
| 1 | 规范一致性 | 不加代码注释（项目规范）；命名/日志风格对齐既有文件（DualLoss 类结构、eval 打印 [eval] 前缀）；不修改 criterion/AGENTS.md 既有条目之外的事实 | HIGH |
| 2 | 模块边界 | criterion 只做损失（不 import data/models/training）；train.py 只接线；eval 只推理；training/models/data/log_manager 零改动；无循环依赖 | HIGH |
| 3 | 数据安全 | 无硬编码凭证；不触碰 full_base/full_dual 的 tmux 会话与 run 目录（对照评估只读） | HIGH |
| 4 | 导入合规 | 无通配符 import；pure_reg_loss.py 仅 import torch/nn（不 import EMDLoss）；train.py 新增 import 无循环 | MEDIUM |
| 5 | 错误处理 | 退化分支显式返回 zeros 不静默吞异常；eval 缺 PURE_REG 键用 get 默认 False 显式兼容；日志打印激活的 criterion 分支 | MEDIUM |
| 6 | 性能风险 | 冒烟固定 --num_workers 0（Windows spawn）；PureRegLoss 不实例化 EMDLoss（参数量零增加）；分类头无梯度不产生额外反向开销；无 O(N²) 扫描；不触碰 parquet 全量加载逻辑 | MEDIUM |

### TDD 要点（criterion ⚡full 触发 → test_scope: full）

PureRegLoss 数值行为单测（tests/unit/criterion/test_criterion_pure_reg_loss.py，unittest，先 RED 后 GREEN）：

1. huber 值 == nn.HuberLoss(delta) 直接计算（places=5，对照 test_criterion_dual_loss.py:12-29 写法）
2. 缺 ret_pred / targets_ret 退化：返回三元组且 total=reg_part=cls_zero=.item()==0.0
3. is_dual_head 判别：getattr(实例, 'is_dual_head') is True；模拟 trainer._compute_loss 4 参调用返回 tuple[0] 为标量 tensor
4. 模型前向 shape 不受影响：最小 ModelConfig（featurenum=10, seq_len=20, num_classes=52）实例化 CNNTransformer，forward 输入 [B,10,20] 断言返回 (logits[B,52], ret_pred[B])；PureRegLoss backward 后 logits.grad is None、ret_pred.grad 非 None
5. dtype/device 对齐：ret_pred/targets_ret 传 float64 等异 dtype 时 reshape(-1)+to() 不炸（参照 dual_loss.py:39-41）

eval pure_reg 分支逻辑（不写单测，T04 端到端验证）：

- 旧 ckpt（config.json 无 PURE_REG）默认 False 走 softmax·CENTERS52 —— base/dual 对照数值一致
- pure_reg ckpt：exp_ret == ret_pred，report 含 mode 标志与"分类头未训练"标注，52acc ≈ 1/52 随机水平佐证

## 验证命令清单（均不干扰后台训练）

```bash
uv run --project . python -m pytest tests/unit/criterion/ -q                     # T01
uv run --project . python -m py_compile criterion/pure_reg_loss.py train.py scripts/eval_bins_mapping.py  # T01-T03
uv run --project . python train.py --help                                        # T02（含 --pure_reg）
uv run --project . python train.py --max_codes 200 --epochs 1 --batch_size 512 --num_workers 0 --pure_reg  # T04
uv run --project . python scripts/eval_bins_mapping.py --checkpoint <run>/best_model.pth --max_codes 200   # T04
uv run ruff check .                                                              # 全任务
```

