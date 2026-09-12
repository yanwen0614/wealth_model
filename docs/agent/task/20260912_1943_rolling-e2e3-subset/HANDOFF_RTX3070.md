# Handoff — E1–E4 全量对照实验（RTX3070 接手）

> 生成：2026-09-12（GTX 970M 侧中止后移交）。任务目录：`docs/agent/task/20260912_1943_rolling-e2e3-subset/`

## 1. 当前状态

- 分支：`feature/rolling-normalization-cnn`（已 push，远端同步，见 §5）。
- 代码（T01–T04）全部 Quality Gate PASS：`--rolling_scope e2/e3/e4`、`--seed`、产物按 `logs/rolling_{scope}/` 隔离、eval 回退指向新 e4 路径。默认行为冻结（rolling 无 scope = E4，per_code 零改动）。
- GTX 970M 侧已中止：实测 3.83it/s、单 epoch≈2.9h，4 组需 1–2 周。tmux 会话已 kill，无残留进程。
- E1 在 970M 上仅跑出部分产物（`logs/run_20260912_205911/`，未完成），**不要复用**，在 3070 上重跑全部四组。

## 2. 3070 上机步骤

```bash
cd <cnn-repo> && git fetch origin && git checkout feature/rolling-normalization-cnn && git pull
uv sync --offline   # 离线可用；若失败改在线 uv sync
uv run --project . python -c "import torch; print(torch.cuda.is_available())"  # 必须 True
ls -lh data/test/train_data/   # 确认 parquet 存在（win32 走 Z:，linux 走软链接→../quant）
```

## 3. 起跑命令（E1→E2→E3→E4 串行，失败即停）

```bash
tmux new-session -d -s cnn_e1e4 -c "$PWD" "uv run --project . python -u train.py --normalize per_code --seed 42 --epochs 50 --batch_size 256 --num_workers 0 > /tmp/opencode/e1e4_chain.log 2>&1 && uv run --project . python -u train.py --normalize rolling --rolling_scope e2 --seed 42 --epochs 50 --batch_size 256 --num_workers 0 >> /tmp/opencode/e1e4_chain.log 2>&1 && uv run --project . python -u train.py --normalize rolling --rolling_scope e3 --seed 42 --epochs 50 --batch_size 256 --num_workers 0 >> /tmp/opencode/e1e4_chain.log 2>&1 && uv run --project . python -u train.py --normalize rolling --rolling_scope e4 --seed 42 --epochs 50 --batch_size 256 --num_workers 0 >> /tmp/opencode/e1e4_chain.log 2>&1; echo CHAIN_EXIT_CODE=\$? >> /tmp/opencode/e1e4_chain.log"
```

- 固定变量：seed 42 / epochs 50 / patience 10 / batch 256 / num_workers 0（workers 未播种，统一 0 保可比）。
- 产物：E1 → `logs/run_*/`；E2/E3/E4 → `logs/rolling_e{2,3,4}/run_*/`。每组 `config.json:preprocessing` 含 mode/scope/seed/digest/identity/rolling_audit。
- 预计：3070 单 epoch 约 20–40 分钟；早停 patience=10，单组数小时～1 天，四组几天内。

## 4. 跟踪命令（sleep 链式，禁 while）

```bash
sleep 600 && tmux capture-pane -t cnn_e1e4 -p | tail -20
sleep 600 && tail -5 /tmp/opencode/e1e4_chain.log
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv
```

## 5. 已 push 的 commits（pull 后核对）

```
9a7c1ba docs: abort E1-E4 on GTX970M (3.83it/s too slow), move to RTX3070
4cc9632 feat: rolling-e2e3-subset E2/E3 scope switch + seed + eval isolation
4ffcd0f docs: add plan for rolling-e2e3-subset
ae4d675 docs: sync stale task status (superseded/done/deferred)
```

核对：`git log --oneline -4` 与上一致；`git status --porcelain` 为空。

## 6. 四组跑完后的评估（PLAN.md §评估命令）

```bash
bash scripts/run_eval_full.sh logs/run_<E1>/best_model.pth 2026-01-01 2026-08-31
bash scripts/run_eval_full.sh logs/rolling_e2/<E2>/best_model.pth 2026-01-01 2026-08-31
bash scripts/run_eval_full.sh logs/rolling_e3/<E3>/best_model.pth 2026-01-01 2026-08-31
bash scripts/run_eval_full.sh logs/rolling_e4/<run>/best_model.pth 2026-01-01 2026-08-31
jq .preprocessing.rolling_audit <run>/config.json   # fallback_ratio / rolling_values
```

五项记录：IC/ICIR、top-bottom、换手成本后收益、fallback 比例、winsor 统计。回测口径：T 决策→T+1 open 买→T+6 open 卖。

## 7. 已知遗留（不阻塞训练，评估后处理）

- `train.py` DataLoader workers 未播种（对照统一 num_workers=0 即可比）。
- `ROLLING_SCOPES` 与 `ROLLING_SCOPE_FEATURES` 键集合双定义（漂移风险，当前一致）。
- `scripts/run_eval_pipeline.py` 的 ruff/pyright 告警均为改前既有。
- 旧 `logs/rolling/` 目录已废弃（被 `logs/rolling_e4/` 取代），勿用。
