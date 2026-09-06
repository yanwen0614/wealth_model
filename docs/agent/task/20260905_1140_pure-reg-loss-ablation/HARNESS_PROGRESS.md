# 进度跟踪 — pure-reg-loss-ablation

> 生成时间：2026-09-05 11:40
> 需求：新增"纯回归损失"消融实验（base=EMD 分类 / dual=EMD+λ·Huber / pure_reg=Huber 回归）。模型层与 training 层零改动，经 is_dual_head 判别兼容现有 Trainer；eval 链路按 checkpoint config.json 的 PURE_REG 自动切换 exp_ret 来源（ret_pred 替代 softmax·CENTERS52）。

## 任务列表

| Task | 名称 | 状态 | Quality Gate | 备注 |
|------|------|------|--------------|------|
| T01 | PureRegLoss + TDD 单测 | done | PASS | 5 测试 0.17s 全绿 |
| T02 | train.py 接线 PURE_REG | done | PASS | 5 处接线 +8/-1 |
| T03 | eval_bins_mapping.py pure_reg 分支 | done | PASS | ret_pred 排序 + 旧 ckpt 回归一致 |
| T04 | 冒烟 + eval 端到端验证 | done | PASS | run_20260905_121056，config PURE_REG:true |

> 2026-09-05 12:30 全部完成。VERDICT=PASS（6 关卡/3 验证/TDD/T04 四项）。非 git 仓库，无提交环节。
> 遗留：2 条 LOW 观察项（eval 空列表边界不可达、PLAN 文本等价偏差），未达 MISTAKES.md 阈值。
> 后续：full_base 早停后启动 pure_reg 全量训练（主编排器负责）。

## 执行详情

### T01: PureRegLoss + TDD 单测
- **状态**：pending
- **依赖**：无
- **文件**：
  - criterion/pure_reg_loss.py (create)
  - tests/unit/criterion/test_criterion_pure_reg_loss.py (create)
- **预估行数**：+90
- **验收标准**：
  1. PureRegLoss total/reg_part == nn.HuberLoss(delta)(ret_pred, targets_ret)，places=5
  2. 缺 ret_pred/targets_ret 退化返回三元组，各项 .item()==0.0
  3. getattr(criterion, 'is_dual_head') is True；4 参调用返回 tuple[0] 为标量
  4. 最小 ModelConfig CNNTransformer forward [B,10,20] -> (logits[B,52], ret_pred[B])；backward 后 logits.grad is None、ret_pred.grad 非 None
  5. pytest tests/unit/criterion/ 全绿；ruff check 通过
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T02: train.py 接线 PURE_REG
- **状态**：pending
- **依赖**：T01
- **文件**：
  - train.py (modify)
- **预估行数**：+10/-3
- **验收标准**：
  1. py_compile 通过；--help 含 --pure_reg
  2. 冒烟 run 目录 config.json 含 "PURE_REG": true（LoggerManager 自动持久化，log_manager/__init__.py:65-70）
  3. 不带 --pure_reg 时走原 EMD/Dual 分支，行为与现状一致
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T03: eval_bins_mapping.py pure_reg 分支
- **状态**：pending
- **依赖**：T01（联调依赖 T02）
- **文件**：
  - scripts/eval_bins_mapping.py (modify)
- **预估行数**：+15/-4
- **验收标准**：
  1. py_compile 通过
  2. base/dual 旧 ckpt（config.json 无 PURE_REG 键）评估结果与改动前一致
  3. pure_reg ckpt 下 exp_ret=ret_pred 路径生效，report 含 mode 与"分类头未训练"标注
- **Quality Gate 结果**：-
- **修复轮次**：0/2

### T04: 冒烟 + eval 端到端验证
- **状态**：pending
- **依赖**：T01, T02, T03
- **文件**：无（运行验证；日志落 logs/）
- **预估行数**：0
- **验收标准**：
  1. uv run --project . python train.py --max_codes 200 --epochs 1 --batch_size 512 --num_workers 0 --pure_reg 跑通无 NaN
  2. uv run --project . python scripts/eval_bins_mapping.py --checkpoint <pure_reg_run>/best_model.pth --max_codes 200 走 ret_pred 路径
  3. base（run_20260905_025222）/ dual（run_20260905_025822）ckpt 对照评估数值一致（回归不破坏）
  4. ruff check . 通过；52acc ≈ 1/52 佐证分类头未训练
- **Quality Gate 结果**：-
- **修复轮次**：0/2

## 环境注意事项（全程有效）

- full_base（run_20260905_025222）/ full_dual（run_20260905_025822）tmux 后台运行中：验证一律 --num_workers 0、单进程串行、不 kill/重启 tmux、不写其 run 目录（对照评估只读）。
- Windows + num_workers>0 spawn 风险：固定 num_workers 0（eval 脚本默认已是 0）。
- 非 git 仓库：本任务三件套与后续编码均无 commit 环节。
- MISTAKES.md 不存在，留待 QualityGate FAIL 时首次创建。
