#!/usr/bin/env bash
set -euo pipefail
# scripts/run_eval_full.sh — 完整评估链路：scaler → 推理 → OHLC → 回测
# 用法：bash scripts/run_eval_full.sh [checkpoint_path] [start_date] [end_date]
#
# 默认取最新 checkpoint，评估 2026-01-01 ~ 2026-08-31，执行 TopN rolling 回测 + TopN 曲线

CKPT="${1:-}"
START="${2:-2026-01-01}"
END="${3:-2026-08-31}"

CKPT_ARG=""
if [ -n "$CKPT" ]; then
  CKPT_ARG="--checkpoint $CKPT"
fi

echo "=========================================="
echo "完整评估链路"
echo "  checkpoint: ${CKPT:-自动最新}"
echo "  时间范围:   $START ~ $END"
echo "=========================================="

# Step 1: 推理缓存 + OHLC 路径表
echo ""
echo "[Step 1] scaler → 推理缓存 → OHLC 路径表"
uv run --project . python -m scripts.run_eval_pipeline \
  $CKPT_ARG \
  --start "$START" \
  --end "$END" \
  --batch_size 512 \
  --num_workers 0

# 从输出路径推断文件名（与 pipeline 脚本默认一致）
CKPT_BASENAME="latest"
if [ -n "$CKPT" ]; then
  CKPT_BASENAME=$(basename "$CKPT" .pth)
fi
PREDS="logs/preds_${CKPT_BASENAME}_${END}.npz"
OHLC="logs/ohlc_path_${START}_${END}.npz"

# Step 2: TopN rolling 回测
echo ""
echo "[Step 2] TopN rolling 回测"
uv run --project . python -m scripts.run_backtest \
  --preds "$PREDS" \
  --ohlc "$OHLC" \
  --topn 5 10 20 50 100 \
  --cost_rate 0.0015 \
  --horizon 5 \
  --out_dir "logs/backtest_${CKPT_BASENAME}_${START}_${END}"

# Step 3: TopN 收益折线
echo ""
echo "[Step 3] TopN 截面收益折线"
uv run --project . python -m scripts.plot_topn_curve \
  --preds "$PREDS" \
  --labels "${CKPT_BASENAME}" \
  --out "logs/topn_curve_${CKPT_BASENAME}_${START}_${END}.png"

echo ""
echo "=========================================="
echo "完成！产物："
echo "  $PREDS"
echo "  $OHLC"
echo "  logs/backtest_${CKPT_BASENAME}_${START}_${END}/"
echo "  logs/topn_curve_${CKPT_BASENAME}_${START}_${END}.png"
echo "=========================================="
