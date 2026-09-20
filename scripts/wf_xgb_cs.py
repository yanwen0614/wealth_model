"""Walk-forward XGB截面回归：年频 × 固定近5年窗口（用户定稿）。
每折只用决策日前5年拟合X3（device=cuda），预测下一年；
防泄露断言max(train)<min(pred)；产物落logs/wf_annual_fixed5y/。
用法：python -m scripts.wf_xgb_cs --dry_run / （实跑）--out_dir logs/wf_annual_fixed5y
"""
from __future__ import annotations

import argparse
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

FOLDS = [
    {"name": "fold1_val", "train": ("2019-07-01", "2024-06-30"),
     "pred": ("2024-07-01", "2025-06-30")},
    {"name": "fold2_test", "train": ("2020-07-01", "2025-06-30"),
     "pred": ("2025-07-01", "2026-08-31")},
]
X3 = {"n_estimators": 500, "max_depth": 4, "learning_rate": 0.05,
      "min_child_weight": 200, "reg_lambda": 5.0, "subsample": 0.8,
      "colsample_bytree": 1.0}
SAMPLE = 4_000_000


def log(*a):
    print(*a, flush=True)


def load():
    X = np.load("logs/gbdt_cs/X_cs.npy", mmap_mode="r")
    y = np.load("logs/gbdt_cs/y_ret.npy", mmap_mode="r")
    di = np.load("logs/gbdt_cs/date_idx.npy")
    ci = np.load("logs/gbdt_cs/code_idx.npy")
    dates = pd.read_parquet("logs/ic_analysis/dates.parquet")["date"].to_numpy()
    codes = np.load("logs/ic_analysis/codes.npy", allow_pickle=True)
    with open("logs/gbdt_cs/features.json", encoding="utf-8") as fh:
        feats = json.load(fh)["features"]
    return X, np.asarray(y), dates[di], codes[ci], feats


def mask(d, lo, hi):
    return (d >= np.datetime64(lo)) & (d <= np.datetime64(hi))


def clip_train(y, m):
    lo, hi = np.percentile(y[m], [0.5, 99.5])
    return np.clip(y, lo, hi).astype(np.float32), float(lo), float(hi)


def run_fold(X, y, d, c, fold, out_dir, dry=False):
    tr = mask(d, *fold["train"])
    pr = mask(d, *fold["pred"])
    assert int(tr.sum()) > 0 and int(pr.sum()) > 0, f"{fold['name']} 空折"
    assert d[tr].max() < d[pr].min(), "泄露：训练最大日>=预测最小日"
    log(f"[{fold['name']}] train {fold['train']} n={int(tr.sum())} "
        f"pred {fold['pred']} n={int(pr.sum())}")
    if dry:
        return None
    t0 = time.time()
    yc, lo, hi = clip_train(y, tr)
    rng = np.random.default_rng(abs(hash(fold["name"])) % (2 ** 31))
    idx = np.where(tr)[0]
    sub = rng.choice(idx, size=min(SAMPLE, len(idx)), replace=False)
    # 验证用预测段前20%做早停（仍<=决策日，无泄露）
    pidx = np.where(pr)[0]
    cut = int(len(pidx) * 0.2)
    ev = np.sort(pidx)[:cut]
    m = xgb.XGBRegressor(tree_method="hist", device="cuda", eval_metric="rmse",
                         random_state=0, n_jobs=4, early_stopping_rounds=50, **X3)
    m.fit(np.asarray(X[sub]), yc[sub], eval_set=[(np.asarray(X[ev]), yc[ev])],
          verbose=False)
    pred = m.predict(np.asarray(X[pr])).astype(np.float64)
    os.makedirs(out_dir, exist_ok=True)
    np.savez(os.path.join(out_dir, f"preds_{fold['name']}.npz"), exp_ret=pred,
             true_ret=y[pr].astype(np.float64), dates=d[pr].astype("datetime64[us]"),
             codes=c[pr])
    joblib.dump({"config": X3, "clip": [lo, hi], "best_iter": int(m.best_iteration)},
                os.path.join(out_dir, f"model_{fold['name']}.joblib"))
    imp = pd.Series(m.feature_importances_).to_dict()
    log(f"[{fold['name']}] best={m.best_iteration} {round(time.time()-t0,1)}s")
    return {"fold": fold["name"], "best_iter": int(m.best_iteration),
            "importance": {str(k): float(v) for k, v in imp.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry_run", action="store_true")
    ap.add_argument("--out_dir", default="logs/wf_annual_fixed5y")
    args = ap.parse_args()
    X, y, d, c, feats = load()
    log(f"rows {len(y)} feats {feats}")
    os.makedirs(args.out_dir, exist_ok=True)
    recs = []
    for fold in FOLDS:
        r = run_fold(X, y, d, c, fold, args.out_dir, dry=args.dry_run)
        if r:
            recs.append(r)
    if recs:
        # 拼 test/val 为三分口径做头对头
        for tag, folds in (("val", ["fold1_val"]), ("test", ["fold2_test"])):
            parts = [np.load(os.path.join(args.out_dir, f"preds_{f}.npz")) for f in folds]
            exp = np.concatenate([p["exp_ret"] for p in parts])
            tru = np.concatenate([p["true_ret"] for p in parts])
            dts = np.concatenate([p["dates"] for p in parts])
            cds = np.concatenate([p["codes"] for p in parts])
            np.savez(os.path.join(args.out_dir, f"preds_wf_{tag}.npz"),
                     exp_ret=exp, true_ret=tru, dates=dts, codes=cds)
        with open(os.path.join(args.out_dir, "fold_info.json"), "w") as fh:
            json.dump(recs, fh, indent=2)
        log("saved", args.out_dir)


if __name__ == "__main__":
    main()
