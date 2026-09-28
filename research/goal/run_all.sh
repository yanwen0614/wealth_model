#!/usr/bin/env bash
# 一键复现（smoke 口径，默认不覆盖 artifacts/* 真实产物，全部 smoke 输出进 /tmp/goal_smoke）。
# 全量口径（需数十分钟~数小时，不必重跑）见各节 FULL 注释。
set -euo pipefail

PY=/home/starcyan/code/cnn/.venv/bin/python
ROOT="$(cd "$(dirname "$0")" && pwd)"
SMOKE=/tmp/goal_smoke

mkdir -p "$SMOKE/synth" "$SMOKE/eng_good" "$SMOKE/eng_real"

echo "=== [1/4] prep --check (sample_100 快检) ==="
$PY "$ROOT/data/prep.py" --parquet "$ROOT/data/sample_100.parquet" \
  --check --check-out "$SMOKE/data_check.json" --scaler-out "$SMOKE/scaler.pkl"
# FULL: $PY data/prep.py --check --estimate-windows-codes 200   # 全量 train_data.parquet，回写 artifacts/baseline/data_check.json + artifacts/baseline/scaler.pkl

echo "=== [2/4] baseline_hgb --smoke ==="
# smoke 消费 [1/4] 刚生成的 $SMOKE/scaler.pkl（全量缺省 artifacts/scaler.pkl 另见 FULL 行）。
$PY "$ROOT/models/baseline_hgb.py" --smoke --scaler "$SMOKE/scaler.pkl" \
  --pred-out "$SMOKE/pred.parquet" --metrics-out "$SMOKE/metrics.json"
# FULL: $PY models/baseline_hgb.py --full   # 全量，回写 artifacts/baseline/pred_test.parquet + artifacts/baseline/metrics.json（约10分钟级）

echo "=== [3/4] backtest 合成自检 (good/flat/inv) ==="
$PY "$ROOT/backtest/make_synthetic.py" --outdir "$SMOKE/synth"
# G02：默认 adapter 路径需 OHLC 行情，合成 pred 只有 score 列，故从 synth_good
# 确定性派生配套行情（同码同日期，价格单调漂移保证可成交；STK 无后缀码走
# provider limit_unknown 计数通道，不中断）。
$PY -c "
import pandas as pd
pred = pd.read_parquet('$SMOKE/synth/synth_good.parquet')
frames = []
for code_index, (code, g) in enumerate(sorted(pred.groupby('code'), key=lambda kv: kv[0])):
    g = g.sort_values('kline_time').reset_index(drop=True)
    base = 10.0 + (code_index % 50)
    close = base * (1.0 + 0.0005 * g.index.to_numpy())
    frames.append(pd.DataFrame({'code': code, 'kline_time': pd.to_datetime(g['kline_time']),
        'open': close, 'high': close * 1.001, 'low': close * 0.999, 'close': close,
        'volume': 2_000_000.0, 'amount': 2_000_000.0 * close, 'is_trading': True}))
pd.concat(frames, ignore_index=True).to_parquet('$SMOKE/synth/synth_market.parquet', index=False)
print('synth market rows:', len(pred))
"
$PY "$ROOT/backtest/engine.py" --pred "$SMOKE/synth/synth_good.parquet" \
  --market "$SMOKE/synth/synth_market.parquet" --out "$SMOKE/eng_good"
# LEGACY(旧 quintile 体，已退役，需 GOAL_ALLOW_LEGACY=1，仅排障时手动开)：
# $PY "$ROOT/backtest/engine.py" --pred "$SMOKE/synth/synth_good.parquet" --out "$SMOKE/eng_good" --legacy

echo "=== [4/4] engine 真实回测一致性 (adapter 口径：pred_test + train_data -> /tmp) ==="
$PY "$ROOT/backtest/engine.py" --pred "$ROOT/artifacts/baseline/pred_test.parquet" \
  --market "$ROOT/data/train_data.parquet" --out "$SMOKE/eng_real"
$PY -c "
import json
b = json.load(open('$SMOKE/eng_real/backtest.json'))
m = json.load(open('$SMOKE/eng_real/manifest.json'))
assert b['engine'] == 'goal_adapter', b.get('engine')
assert 'legacy' not in b, 'legacy 口径泄漏'
assert {'config_hash', 'data_fingerprint', 'order_entry', 'strategy',
        'run_id', 'created_at', 'provenance'} <= set(m), set(m)
assert m['config_hash'] == b['config_hash'] and m['data_fingerprint'] == b['data_fingerprint']
assert b['final_nav'] > 0, b.get('final_nav')
print('adapter backtest OK:', {'engine': b['engine'], 'strategy': b.get('strategy'),
      'final_nav': round(b['final_nav'], 2)})
"
# FULL(重生成产物): $PY backtest/engine.py --pred artifacts/baseline/pred_test.parquet --market data/train_data.parquet --out artifacts/baseline
# LEGACY(旧口径一致性断言，已退役：旧 backtest.json 为 quintile 键，与 adapter 口径不可比)：
# a = json.load(open('$ROOT/artifacts/baseline/backtest.json')); b = json.load(open('$SMOKE/eng_real/backtest.json'))
# assert a.keys() == b.keys()

echo "ALL SMOKE OK"
