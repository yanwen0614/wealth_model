# 全量训练 TODO（换大GPU后执行）

> 背景：双头52+1已落地 `bb19df2`，冒烟20股1epoch持平（baseline Val0.0542/11.77% vs dual Val0.0549/10.73%，RankIC +0.13 vs -0.09，1epoch噪声）。970M 3GB估算80~97min/epoch，全量50epoch约75h， too重，换卡后跑。

## Step1 — 200股3epoch验证（约30min）
```bash
uv run --project . python train.py --max_codes 200 --epochs 3 --batch_size 256 --num_workers 4
uv run --project . python train.py --max_codes 200 --epochs 3 --batch_size 256 --num_workers 4 --dual_head --lambda_reg 0.2
uv run --project . python scripts/eval_bins_mapping.py --checkpoint logs/run_xxx/best_model.pth --max_codes 200 --num_workers 4
```
验收：双头RankIC转正、Top10%为正率>50%再继续；否则λ降到0.05~0.1重跑。

## Step2 — 全量baseline（约1.5天，早停15~25epoch）
```bash
tmux new-session -d -s cnn_full_base -c "$PWD" "uv run --project . python train.py --epochs 50 --batch_size 256 --num_workers 4 > /tmp/opencode/full_base.txt 2>&1; echo EXIT_CODE=\$? >> /tmp/opencode/full_base.txt"
sleep 900 && tmux capture-pane -t cnn_full_base -p | tail -40
```

## Step3 — 全量dual（约1.5天）
```bash
tmux new-session -d -s cnn_full_dual -c "$PWD" "uv run --project . python train.py --epochs 50 --batch_size 256 --num_workers 4 --dual_head --lambda_reg 0.2 > /tmp/opencode/full_dual.txt 2>&1; echo EXIT_CODE=\$? >> /tmp/opencode/full_dual.txt"
```

## 对比指标
`scripts/eval_bins_mapping.py`输出52acc/11acc/13acc/RankIC/五分位/Top10%mean/为正率/spread，填下表决策：
|  | 52acc | 11acc | 13acc | RankIC | Top10%mean | 为正率 |
|---|---|---|---|---|---|---|
| base |  |  |  |  |  |  |
| dual |  |  |  |  |  |  |
