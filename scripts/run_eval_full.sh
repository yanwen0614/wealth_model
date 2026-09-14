#!/usr/bin/env bash
set -euo pipefail
# scripts/run_eval_full.sh — 完整评估链路：scaler → 推理 → OHLC → 回测
# 用法：bash scripts/run_eval_full.sh [checkpoint_path] [start_date] [end_date]
#
# 默认取最新 checkpoint，评估 2026-01-01 ~ 2026-08-31，执行 TopN rolling 回测 + TopN 曲线
#
# preprocessing 说明：本脚本按 checkpoint 通用（位置参数 $1 直接透传 pipeline），
#   mode（relative/per_code/rolling）与 scope（e0..e5）从同目录 config.json 的
#   preprocessing.mode/scope 解析并校验，异 scope/mode 直接报错，无需 --scope 硬改。
#   per_code → logs/run_xxx；rolling → logs/rolling_e{0..5}/run_xxx；relative → logs/relative/run_xxx。
#
# 多臂评估命令（同名 best_model.pth 会互相覆盖 preds，故按目录派生唯一 --preds_out）：
#   bash scripts/run_eval_full.sh logs/rolling_e0/<run>/best_model.pth 2026-01-01 2026-08-31
#   bash scripts/run_eval_full.sh logs/rolling_e2/<run>/best_model.pth 2026-01-01 2026-08-31
#   bash scripts/run_eval_full.sh logs/rolling_e5/<run>/best_model.pth 2026-01-01 2026-08-31
#   bash scripts/run_eval_full.sh logs/relative/<run>/best_model.pth 2026-01-01 2026-08-31
#
# 五项取数（见 run_eval_pipeline.py 模块 docstring）：
#   IC/ICIR → eval 报告 rank_ic_exp_vs_true + xs_rank_ic_*；
#   top-bottom → top10_bottom10_spread + xs_spread_*；
#   换手成本后收益 → Step 2 metrics.json（逐笔 A 股费用模型：佣金万2.5 最低5元 + 卖出印花税万2.5）；
#   fallback 比例 → jq .preprocessing.rolling_audit.<run>/config.json（fallback_ratio，仅 rolling）；
#   winsor 统计 → 同一 rolling_audit（constant_iqr_values/missing_values）。
# 回测口径（引用 backtest/engine.py，不重实现）：T 日决策→T+1 open 买→T+6 open 卖（horizon=5）。

CKPT="${1:-}"
START="${2:-2026-01-01}"
END="${3:-2026-08-31}"

if [ -n "$CKPT" ]; then
  CKPT_ARG="--checkpoint $CKPT"
  CKPT_DIR=$(dirname "$CKPT")
  CKPT_PARENT=$(basename "$(dirname "$CKPT_DIR")")
  # 同名 best_model.pth 按父目录+运行目录派生唯一标签，避免 preds/回测产物互相覆盖
  if [ "$CKPT_PARENT" = "." ] || [ "$CKPT_PARENT" = "logs" ]; then
    RUN_TAG=$(basename "$CKPT_DIR")
  else
    RUN_TAG="${CKPT_PARENT}_$(basename "$CKPT_DIR")"
  fi
else
  CKPT_ARG=""
  RUN_TAG="latest"
fi

PREDS="logs/preds_${RUN_TAG}_${END}.npz"
OHLC="logs/ohlc_path_${START}_${END}.npz"

echo "=========================================="
echo "完整评估链路"
echo "  checkpoint: ${CKPT:-自动最新}"
echo "  时间范围:   $START ~ $END"
echo "  preds:      $PREDS"
echo "=========================================="

# Step 1: 推理缓存 + OHLC 路径表（显式 --preds_out 防同名 best_model.pth 覆盖）
echo ""
echo "[Step 1] scaler → 推理缓存 → OHLC 路径表"
uv run --project . python -m scripts.run_eval_pipeline \
  $CKPT_ARG \
  --start "$START" \
  --end "$END" \
  --preds_out "$PREDS" \
  --batch_size 512 \
  --num_workers 0

# Step 2: TopN rolling 回测
echo ""
echo "[Step 2] TopN rolling 回测"
uv run --project . python -m scripts.run_backtest \
  --preds "$PREDS" \
  --ohlc "$OHLC" \
  --topn 5 10 20 \
  --horizon 5 \
  --out_dir "logs/backtest_${RUN_TAG}_${START}_${END}"

# Step 3: TopN 收益折线
echo ""
echo "[Step 3] TopN 截面收益折线"
uv run --project . python -m scripts.plot_topn_curve \
  --preds "$PREDS" \
  --labels "${RUN_TAG}" \
  --out "logs/topn_curve_${RUN_TAG}_${START}_${END}.png"

echo ""
echo "=========================================="
echo "完成！产物："
echo "  $PREDS"
echo "  $OHLC"
echo "  logs/backtest_${RUN_TAG}_${START}_${END}/"
echo "  logs/topn_curve_${RUN_TAG}_${START}_${END}.png"
echo "=========================================="
