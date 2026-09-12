#!/usr/bin/env bash
set -euo pipefail
# scripts/run_eval_full.sh — 完整评估链路：scaler → 推理 → OHLC → 回测
# 用法：bash scripts/run_eval_full.sh [checkpoint_path] [start_date] [end_date]
#
# 默认取最新 checkpoint，评估 2026-01-01 ~ 2026-08-31，执行 TopN rolling 回测 + TopN 曲线
#
# T04 scope 说明：本脚本已按 checkpoint 通用（位置参数 $1 直接透传 pipeline），
#   无需 --scope 硬改——checkpoint 路径本身已按 scope 隔离
#   （logs/rolling_e2|e3|e4/<run>/best_model.pth），pipeline 从同目录 config.json 的
#   preprocessing.mode/scope 解析并校验，异 scope 直接报错。per_code 路径零改动。
#
# E1–E4 评估命令：
#   bash scripts/run_eval_full.sh logs/rolling_e2/<run>/best_model.pth 2026-01-01 2026-08-31
#   bash scripts/run_eval_full.sh logs/rolling_e3/<run>/best_model.pth 2026-01-01 2026-08-31
#   bash scripts/run_eval_full.sh logs/rolling_e4/<run>/best_model.pth 2026-01-01 2026-08-31
#
# 五项取数（见 run_eval_pipeline.py 模块 docstring）：
#   IC/ICIR → eval 报告 rank_ic_exp_vs_true + xs_rank_ic_*；
#   top-bottom → top10_bottom10_spread + xs_spread_*；
#   换手成本后收益 → Step 2 metrics.json（--cost_rate 0.0015，双边一次性扣减）；
#   fallback 比例 → jq .preprocessing.rolling_audit.<run>/config.json（fallback_ratio）；
#   winsor 统计 → 同一 rolling_audit（constant_iqr_values/missing_values）。
# 回测口径（引用 backtest/engine.py，不重实现）：T 日决策→T+1 open 买→T+6 open 卖（horizon=5）。

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
