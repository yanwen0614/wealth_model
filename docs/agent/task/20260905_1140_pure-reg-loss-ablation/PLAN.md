# pure-reg-loss-ablation Implementation Plan

> Generated: 2026-09-05 11:40
> Task Dir: docs/agent/task/20260905_1140_pure-reg-loss-ablation

## Goal

新增"纯回归损失"消融分支 pure_reg，与既有 base（EMD 分类）/ dual（EMD+λ·Huber）构成三组对照：PureRegLoss 仅以 HuberLoss(ret_pred, future_ret) 训练回归头，分类头 logits 不进损失（无梯度、不更新），eval 链路按 checkpoint 同目录 config.json 的 PURE_REG 自动切换 exp_ret 取值路径。模型层与 training 层零改动。

## Architecture

- 模型层零改动：`models/cnn_transformer/model.py:110,130` forward 恒返 `(logits, ret_pred)`，fc_reg 无条件构造。
- criterion 新增 PureRegLoss，接口逐条对齐 `criterion/dual_loss.py`（43 行）约定：`is_dual_head` 类属性、4 参 forward、reshape(-1)、dtype/device 对齐、缺参退化返回三元组 zeros；`Trainer._compute_loss`（`training/trainer.py:33-40`）经 `is_dual_head` 判别自动 4 参调用并取 tuple[0]，training 层零改动。
- train.py 三分支接线：PURE_REG > DUAL_HEAD > EMD；config 经 `LoggerManager._save_config`（`log_manager/__init__.py:65-70` 整体 json.dumps）持久化，PURE_REG 顶层键自动进 config.json。
- eval 侧 `load_run_model_cfg`（`scripts/eval_bins_mapping.py:62-72`）扩展读顶层键；pure_reg 模式 exp_ret 直接取 out[1]（ret_pred），下游 RankIC/TopK/11/13/五分位/截面（166-233 行全部以 exp_ret 为唯一输入）零改动复用。

## Key Decisions

| 决策项 | 选择 | 淘汰方案 | 选择理由 |
|--------|------|----------|----------|
| PureRegLoss 接口形态 | is_dual_head=True + 4 参 forward + 三元组返回，对齐 dual_loss.py:20,31-43 | 继承 DualLoss 关闭 EMD 项 / 新增 is_pure_reg 标志改 Trainer | 零侵入 Trainer（getattr 判别即兼容）；独立类避免实例化 EMD 子模块（pure_reg 不应有 EMD 参数） |
| 缺 ret_pred/targets_ret 行为 | 返回 (zeros, zeros, zeros)，total=0 | 抛异常 | 对齐 dual_loss.py:36-38 退化约定，数据异常不炸训练 |
| PURE_REG 与 DUAL_HEAD 同开 | PURE_REG 优先（if/elif） | assert 互斥报错 | 消融优先级语义简单，日志打印激活分支即可观测 |
| eval 标志读取 | load_run_model_cfg 扩展返回 (mc, run_cfg)，evaluate 读 run_cfg.get("PURE_REG", False) | 二次 IO 重读 config.json / 往 mc 混塞非模型键 | 一次 IO 同时取模型配置与模式标志；不污染 ModelConfig 取值 dict；旧 ckpt 缺键默认 False 向后兼容 |
| pure_reg 下 52acc | 照算，report/打印注明"分类头未训练（pure_reg 模式）" | 直接跳过 52 指标 | 保留可观测性（应≈1/52 随机水平），佐证分类头确实未更新 |
| 分类头不训练机制 | logits 不进损失（无梯度），grad=None 参数 AdamW 自动跳过 | requires_grad=False 手工冻结 fc_cls | 模型层零改动，PyTorch 原生语义 |
| eval 分支测试方式 | 不写单测，T04 端到端验证（含旧 ckpt 回归对照） | 为 eval 脚本建单测 | eval 依赖 torch 加载与数据集，单测成本高收益低；criterion 层已有 TDD 单测兜底核心数值 |

## Impact

| 模块 | 文件 | 操作 | 风险等级 |
|------|------|------|----------|
| criterion | criterion/pure_reg_loss.py | create | medium |
| tests | tests/unit/criterion/test_criterion_pure_reg_loss.py | create | low |
| 根入口 | train.py | modify | high |
| scripts | scripts/eval_bins_mapping.py | modify | medium |
| training | （零改动，_compute_loss 已兼容） | - | - |
| models | （零改动，forward 恒返 tuple） | - | - |
| data | （零改动，(x,y_cls,y_ret) 3 元已就绪） | - | - |
| log_manager | （零改动，仅确认持久化行为） | - | - |

## Task Decomposition

### T01: PureRegLoss + TDD 单测（RED→GREEN）
- **文件**: criterion/pure_reg_loss.py (create), tests/unit/criterion/test_criterion_pure_reg_loss.py (create)
- **描述**: 新建 PureRegLoss(nn.Module)：类属性 is_dual_head=True；__init__(num_classes=52, huber_delta=1.0)（num_classes 仅对齐调用签名，内部不使用）；forward(logits, ret_pred=None, targets_cls=None, targets_ret=None)：ret_pred 或 targets_ret 缺失时返回 (zeros, zeros, zeros)（zeros((), device=logits.device, dtype=logits.dtype)，参照 dual_loss.py:36-38）；否则按 dual_loss.py:39-41 做 reshape(-1)+to(logits.dtype)/to(logits.device, logits.dtype) 对齐，total=reg_part=nn.HuberLoss(delta=huber_delta, reduction="mean")(ret_pred, targets_ret)，cls_zero=zeros；logits 不进任何计算。测试四要点：① huber 值 == nn.HuberLoss 直接计算（places=5，对照 test_criterion_dual_loss.py:23）；② 缺参退化三元组全 0；③ is_dual_head 判别 + 模拟 _compute_loss 4 参调用 tuple[0] 为标量；④ 最小 ModelConfig CNNTransformer forward 形状 [B,10,20]->(logits[B,52], ret_pred[B]) 不受影响，PureRegLoss backward 后 logits.grad is None、ret_pred.grad 非 None。测试风格对齐 tests/unit/criterion/test_criterion_dual_loss.py（unittest、docstring、不加行注释）。
- **依赖**: 无
- **预估行数**: +90（实现 ~35，测试 ~55）
- **验收标准**: ① pytest tests/unit/criterion/ 全绿；② total/reg_part == nn.HuberLoss(delta)(ret_pred, y_ret)；③ 退化分支三元组 .item() 全 0.0；④ getattr(c,'is_dual_head') is True；⑤ backward 后 logits.grad is None、ret_pred.grad 非 None；⑥ 模型 forward 形状断言通过
- **风险因子**: logits 一旦混入计算即引入分类头梯度，破坏消融语义——以 grad 断言把关

### T02: train.py 接线 PURE_REG
- **文件**: train.py (modify)
- **描述**: ① import 区（30-31 行旁）加 from criterion.pure_reg_loss import PureRegLoss；② config 字典（75-77 行旁）加 'PURE_REG': False；③ parse_args（109-113 行旁）加 --pure_reg（store_true，help 对齐 --dual_head 风格），复用既有 --huber_delta；④ config 覆盖区（143-145 行旁）加 config['PURE_REG'] = args.pure_reg；⑤ criterion 选择（236-241 行）改三分支：if config['PURE_REG']: PureRegLoss(num_classes=config['num_classes'], huber_delta=config['HUBER_DELTA']) elif config['DUAL_HEAD']: DualLoss(...) else: EMDLoss(...)；⑥ 激活分支日志（239 行风格）：打印"纯回归 PureRegLoss: Huber(δ=...)，分类头 logits 不参与损失（无梯度）"。确认 log_manager/__init__.py:65-70 _save_config 整体 json.dumps(config) → PURE_REG 自动进 config.json（仅确认，不改 log_manager）。
- **依赖**: T01
- **预估行数**: +10 / -3
- **验收标准**: ① python -m py_compile train.py 通过；② train.py --help 含 --pure_reg；③ 冒烟 run 目录 config.json 含 "PURE_REG": true；④ 不带 --pure_reg 时走原 EMD/Dual 分支，行为与现状一致
- **风险因子**: full_base/full_dual 正在 tmux 后台运行——仅编辑文件不影响已加载进程，严禁 kill/重启 tmux 会话

### T03: eval_bins_mapping.py 接线 pure_reg 分支
- **文件**: scripts/eval_bins_mapping.py (modify)
- **描述**: ① load_run_model_cfg（62-72 行）扩展为返回 (mc, run_cfg)，调用点（118 行）同步解包，pure_reg = run_cfg.get("PURE_REG", False)（旧 ckpt 缺键默认 False 向后兼容）；② 推理循环（146-161 行）：pure_reg 时收集 ret_pred = out[1]（新增 all_ret_pred 列表），softmax/argmax 52 照算；③ exp_ret（166 行）：pure_reg 时 exp_ret = np.concatenate(all_ret_pred)，否则维持 (probs*CENTERS52).sum(axis=1)；下游 RankIC/TopK/11/13/五分位/截面（167-233 行）全以 exp_ret 为输入，零改动；④ report/打印（235-267 行）：pure_reg 时 report 加 "mode": "pure_reg"，52 原样打印行追加"分类头未训练（pure_reg 模式）"标注。
- **依赖**: T01（编码仅依赖 T01 接口约定，可与 T02 并行；联调依赖 T02 产出的 config.json 格式）
- **预估行数**: +15 / -4
- **验收标准**: ① python -m py_compile scripts/eval_bins_mapping.py 通过；② base/dual 旧 ckpt（config.json 无 PURE_REG 键）评估结果与改动前一致；③ pure_reg ckpt 下 exp_ret == ret_pred（--out json 抽查 rank_ic 与 ret_pred spearman 一致）；④ report 含 mode 标志与未训练标注
- **风险因子**: load_run_model_cfg 签名变更波及唯一调用点（118 行）——回归对照用 base/dual 既有 run 目录只读验证

### T04: 冒烟 + eval 端到端验证
- **文件**: 无（验证任务；运行日志落 logs/）
- **描述**: ① uv run --project . python train.py --max_codes 200 --epochs 1 --batch_size 512 --num_workers 0 --pure_reg 冒烟跑通（num_workers 0 规避 Windows spawn）；② uv run --project . python scripts/eval_bins_mapping.py --checkpoint <pure_reg run>/best_model.pth --max_codes 200 确认 pure_reg 分支；③ 对 base（run_20260905_025222）/ dual（run_20260905_025822）旧 ckpt 各跑一次对照评估确认回归不破坏；④ uv run ruff check . 通过；⑤ 52acc ≈ 1/52 随机水平佐证分类头未训练。
- **依赖**: T01, T02, T03
- **预估行数**: 0
- **验收标准**: ① 冒烟 1 epoch 无 NaN、val loss 为 Huber 标量量级；② run 目录 config.json 含 "PURE_REG": true；③ eval 对 pure_reg ckpt 走 ret_pred 路径、对 base/dual ckpt 数值与改动前一致；④ ruff check . 通过
- **风险因子**: 见"风险 Top3"第 1 条——验证全程不得干扰后台全量训练

## 验收标准（总）

1. PureRegLoss 数值 == nn.HuberLoss(delta=HUBER_DELTA)(ret_pred, targets_ret)，退化分支三元组全 0（T01 单测全绿）
2. is_dual_head 判别链路：Trainer._compute_loss 4 参调用、tuple[0] 标量回传（trainer.py:35-39），training/ 零改动
3. 模型 forward 形状不变：[B,45,60] -> (logits[B,52], ret_pred[B])；PureRegLoss backward 仅 ret_pred 有梯度
4. 冒烟 run 目录 config.json 含 PURE_REG 顶层键（log_manager/__init__.py:65-70 整体序列化，已确认）
5. eval pure_reg 分支 exp_ret=ret_pred，RankIC/TopK/11/13 全走 ret_pred；旧 ckpt（缺 PURE_REG 键）回归不破坏
6. 冒烟命令 --max_codes 200 --epochs 1 --batch_size 512 --num_workers 0 --pure_reg 端到端通过

## 风险 Top3

1. **全量训练共机干扰（HIGH）**: full_base（run_20260905_025222）/ full_dual（run_20260905_025822）正在 tmux 后台运行。GPU 峰值 2.4GB/8GB 有余量、CPU 8 核已占 ~50%——冒烟/eval 必须 --num_workers 0、单进程串行、不 kill/重启 tmux、不写其 run 目录（对照评估只读）。
2. **旧 checkpoint 回归破坏（MEDIUM）**: load_run_model_cfg 签名变更 + 推理分支扩展可能波及 base/dual 评估路径——run_cfg.get("PURE_REG", False) 缺键默认走原 softmax·CENTERS52 路径，T04 用既有 run 目录各跑一次对照确认数值一致。
3. **Windows spawn 环境陷阱（MEDIUM）**: Windows 下 DataLoader num_workers>0 触发 spawn re-import 主模块，受限环境曾不稳——所有验证命令固定 --num_workers 0（eval 脚本默认已是 0）；本任务不涉及 torch.compile/triton 路径，如冒烟出现 triton 相关 warning 可忽略（不影响 CPU/CUDA eager 路径）。
