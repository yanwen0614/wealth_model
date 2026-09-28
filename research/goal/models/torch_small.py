"""torch 小模型对照 smoke（非主力）— 所选架构: (a) MLP, 先跑通即选定.

契约: TRAIN 2013~2021 / VAL 2022~2023 / TEST 2024~2025；标签 future_ret_5d；
窗口 SEQ_LEN=60 -> X[45,60]；scaler 只 load 复用不重 fit；仅 sample_100.parquet。

架构 (a) MLP: 每窗口取末日 45 维 + 60 日均值池化 45 维 = 90 维输入，
  90 -> 256 -> ReLU -> 64 -> ReLU -> 1，约 3.9 万参数 (<50 万)。
  选 (a) 不选 (b) 的理由: 输入仅 90 维/窗口 (全窗口 [45,60] 存 float32 约 2GB，
  聚合后仅 ~70MB)，CPU 单 epoch <2 分钟，先跑通即锁定；(b) Tiny-1DCNN
  仅保留为 --arch=tiny-cnn 备选实现（同文件内，未默认启用）。
损失 MSE，AdamW lr=1e-3，batch=512，默认 CPU（3GB GTX 970M 若 OOM 自动转 CPU 并记录），
epochs<=5，VAL loss 早停 patience=2。
输出: artifacts/pred_test_torch.parquet [code,kline_time,score,future_ret_5d,q_true]
      artifacts/metrics_torch.json {val_ic,test_ic,耗时,device,...}
--smoke: sample_100 上单 epoch 验证（30 分钟内），全程计时。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from vendor_scaler import (
    PerCodeGroupedScaler,  # 零 cnn 依赖的 vendor 拷贝
)

SEQ_LEN = 60
HORIZON = 5
SPLITS = {
    "TRAIN": ("2013-01-01", "2021-12-31"),
    "VAL": ("2022-01-01", "2023-12-31"),
    "TEST": ("2024-01-01", "2025-12-31"),
}
Y_CLIP = 1.0  # 仅防极端值安全兜底，样本实测 |y|<=0.34，基本无截断


# ---------------- 模型 ----------------
class MLP90(nn.Module):
    """(a) MLP: 90维(末日45+均值池化45) -> 256 -> 64 -> 1。"""

    def __init__(self, in_dim: int = 90):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


class TinyCNN(nn.Module):
    """(b) 备选: 2层Conv1d(45->64->64,k=3,pad=1)+全局均值池化+Linear->1。默认不启用。"""

    def __init__(self, in_ch: int = 45):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_ch, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(64, 64, kernel_size=3, padding=1),
            nn.ReLU(),
        )
        self.head = nn.Linear(64, 1)

    def forward(self, x):  # x: [B,45,60]
        h = self.conv(x).mean(dim=-1)
        return self.head(h).squeeze(-1)


def count_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


# ---------------- 数据 ----------------
def add_future_ret_within_split(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values(["code", "kline_time"]).copy()
    g["future_ret_5d"] = np.nan
    for _code, grp in g.groupby("code", sort=False):
        idx = grp.index.values
        is_tr = grp["is_trading"].values.astype(bool)
        close = grp["close"].values.astype(np.float64)
        n = len(grp)
        fr = np.full(n, np.nan)
        for t in range(n - HORIZON):
            if is_tr[t : t + HORIZON + 1].all():
                c0, c5 = close[t], close[t + HORIZON]
                if np.isfinite(c0) and np.isfinite(c5) and c0 != 0:
                    fr[t] = c5 / c0 - 1.0
        g.loc[idx, "future_ret_5d"] = fr
    return g


def build_mlp_split(
    df_split: pd.DataFrame, feature_cols: list, scaler: PerCodeGroupedScaler
):
    """每股 transform 后枚举窗口，返回 X[ N,90 ]、y、code、kline_time（末日t）。"""
    Xs, ys, codes, times = [], [], [], []
    for code, grp in df_split.groupby("code", sort=False):
        grp = grp.sort_values("kline_time")
        feat = grp[feature_cols].values.astype(np.float64)
        close = grp["close"].values.astype(np.float64)
        is_tr = grp["is_trading"].values.astype(bool)
        fr = grp["future_ret_5d"].values.astype(np.float64)
        kt = grp["kline_time"].values
        n = len(grp)
        if n < SEQ_LEN + HORIZON:
            continue
        F = scaler.transform_code(cast(str, code), feat, feature_cols, close).astype(np.float64)  # [N,45]
        bad = (~is_tr).astype(np.int64)
        cs = np.concatenate([[0], np.cumsum(bad)])
        csF = np.concatenate([np.zeros((1, F.shape[1])), np.cumsum(F, axis=0)], axis=0)
        for t in range(SEQ_LEN - 1, n - HORIZON):
            a, b = t - SEQ_LEN + 1, t + HORIZON
            if cs[b + 1] - cs[a] != 0:
                continue
            c0, c5 = close[t], close[t + HORIZON]
            if not (np.isfinite(c0) and np.isfinite(c5) and c0 != 0):
                continue
            y = fr[t]
            if not np.isfinite(y):
                continue
            last = F[t]
            mean = (csF[t + 1] - csF[a]) / SEQ_LEN
            Xs.append(np.concatenate([last, mean]).astype(np.float32))
            ys.append(float(np.clip(y, -Y_CLIP, Y_CLIP)))
            codes.append(code)
            times.append(kt[t])
    if not Xs:
        return (
            np.zeros((0, 90), np.float32),
            np.zeros((0,), np.float32),
            np.array([]),
            np.array([]),
        )
    return (
        np.stack(Xs).astype(np.float32),
        np.array(ys, dtype=np.float32),
        np.array(codes),
        np.array(times),
    )


def assign_q_true(dates: np.ndarray, y: np.ndarray) -> np.ndarray:
    """每 kline_time 截面 qcut(future_ret,5)，不足5行/去重不足5类则该日 q_true=-1。"""
    q = np.full(len(y), -1, dtype=np.int64)
    df = pd.DataFrame({"d": pd.to_datetime(dates), "y": y})
    for _d, grp in df.groupby("d", sort=False):
        if len(grp) < 5:
            continue
        try:
            qq = cast(Any, pd.qcut(grp["y"], 5, labels=[0, 1, 2, 3, 4], duplicates="drop"))
        except Exception:  # noqa: BLE001, S112 -- 退化截面跳过
            continue
        if getattr(qq, "cat", None) is not None and len(qq.cat.categories) != 5:
            continue
        vals = qq.values
        for idx, v in zip(grp.index.values, vals):
            if not pd.isna(v):
                q[idx] = int(v)
    return q


def daily_ic(dates: np.ndarray, score: np.ndarray, y: np.ndarray):
    """逐日截面 Spearman（rank+Pearson手算，零scipy依赖）均值=IC，std→IR。"""
    df = pd.DataFrame(
        {"d": pd.to_datetime(dates), "s": score.astype(np.float64), "y": y.astype(np.float64)}
    )
    ics = []
    for _d, grp in df.groupby("d", sort=False):
        if len(grp) < 5:
            continue
        rs = grp["s"].rank().to_numpy(dtype=np.float64)
        ry = grp["y"].rank().to_numpy(dtype=np.float64)
        rs = rs - rs.mean()
        ry = ry - ry.mean()
        denom = np.sqrt((rs**2).sum() * (ry**2).sum())
        if denom == 0 or not np.isfinite(denom):
            continue
        r = float((rs * ry).sum() / denom)
        if np.isfinite(r):
            ics.append(r)
    ics = np.array(ics)
    if len(ics) == 0:
        return 0.0, 0.0, 0
    return float(ics.mean()), float(ics.mean() / (ics.std() + 1e-12)), len(ics)


@torch.no_grad()
def predict_loader(model, loader, device) -> np.ndarray:
    model.eval()
    outs = []
    for (xb,) in loader:
        outs.append(model(xb.to(device)).float().cpu().numpy())
    return np.concatenate(outs) if outs else np.zeros((0,), np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(ROOT / "data" / "sample_100.parquet"))
    ap.add_argument("--scaler", default=str(ROOT / "artifacts" / "scaler.pkl"))
    ap.add_argument("--out-pred", default=str(ROOT / "artifacts" / "pred_test_torch.parquet"))
    ap.add_argument("--out-metrics", default=str(ROOT / "artifacts" / "metrics_torch.json"))
    ap.add_argument("--arch", choices=["mlp", "tiny-cnn"], default="mlp")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    ap.add_argument("--smoke", action="store_true", help="单epoch验证")
    args = ap.parse_args()

    t_all = time.time()
    if args.smoke:
        args.epochs = 1
    assert args.epochs <= 5, "epochs<=5（契约上限）"
    torch.manual_seed(args.seed)

    # device：默认CPU；cuda/auto 若 OOM 则回退 CPU 并记录
    dev_req = args.device
    device = torch.device("cpu")
    if args.device in ("cuda", "auto"):
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    oom_fallback = False

    t0 = time.time()
    scaler = PerCodeGroupedScaler.load(args.scaler)  # load复用，不重fit
    feature_cols = list(scaler.feature_cols)  # 39列输入
    assert len(scaler.feature_cols_out) == 45, "scaler输出须45维"
    use_cols = list(dict.fromkeys(["code", "kline_time", "close", "is_trading"] + feature_cols))
    df = pq.read_table(args.sample, columns=use_cols).to_pandas()
    df["kline_time"] = pd.to_datetime(df["kline_time"])
    t_read = time.time() - t0

    if args.arch != "mlp":
        raise SystemExit("本run锁定架构(a)MLP；tiny-cnn仅备选实现，未进入训练路径")

    # 切分 + 窗口（各split内各自算future_ret，不跨split）
    t0 = time.time()
    bundle = {}
    for name, (s, e) in SPLITS.items():
        m = (df["kline_time"] >= pd.Timestamp(s)) & (df["kline_time"] <= pd.Timestamp(e))
        sdf = add_future_ret_within_split(df.loc[m].copy())
        X, y, codes, times = build_mlp_split(sdf, feature_cols, scaler)
        bundle[name] = (X, y, codes, times)
        print(f"[{name}] windows={len(X):,}", flush=True)
    t_build = time.time() - t0
    Xtr, ytr, _, _ = bundle["TRAIN"]
    Xva, yva, _, dva = bundle["VAL"]
    Xte, yte, cte, dte = bundle["TEST"]
    assert len(Xtr) > 0 and len(Xva) > 0 and len(Xte) > 0, "某split窗口数为0，BLOCKED"

    model = MLP90(in_dim=Xtr.shape[1])
    n_params = count_params(model)
    assert n_params < 500_000, f"参数量{n_params}超50万上限"
    print(f"[arch] mlp90 dims={Xtr.shape[1]} params={n_params}", flush=True)

    def run_train(dev: torch.device):
        m = MLP90(in_dim=Xtr.shape[1]).to(dev)
        opt = torch.optim.AdamW(m.parameters(), lr=args.lr)
        loss_fn = nn.MSELoss()
        tr_loader = DataLoader(
            TensorDataset(torch.from_numpy(Xtr), torch.from_numpy(ytr)),
            batch_size=args.batch, shuffle=True,
            generator=torch.Generator().manual_seed(args.seed),
        )
        va_loader = DataLoader(TensorDataset(torch.from_numpy(Xva)), batch_size=4096)
        best, best_state, bad = float("inf"), None, 0
        epochs_run = 0
        for ep in range(args.epochs):
            m.train()
            tot, nb = 0.0, 0
            for xb, yb in tr_loader:
                xb, yb = xb.to(dev), yb.to(dev)
                opt.zero_grad()
                loss = loss_fn(m(xb), yb)
                loss.backward()
                opt.step()
                tot += loss.item() * len(xb)
                nb += len(xb)
            m.eval()
            with torch.no_grad():
                pv = predict_loader(m, va_loader, dev)
                va_loss = float(np.mean((pv - yva) ** 2))
            epochs_run += 1
            print(f"[ep{ep+1}] train_mse={tot/max(nb,1):.6f} val_mse={va_loss:.6f}", flush=True)
            if va_loss < best - 1e-9:
                best, best_state, bad = va_loss, {k: v.cpu() for k, v in m.state_dict().items()}, 0
            else:
                bad += 1
                if bad >= 2:
                    print(f"[early-stop] patience=2 at ep{ep+1}", flush=True)
                    break
        m.load_state_dict(cast(Any, best_state))
        return m, epochs_run

    t0 = time.time()
    try:
        model, epochs_run = run_train(device)
        device_actual = str(device)
    except (RuntimeError, torch.cuda.OutOfMemoryError) as ex:
        if "out of memory" in str(ex).lower() and str(device) != "cpu":
            torch.cuda.empty_cache()
            oom_fallback = True
            device = torch.device("cpu")
            model, epochs_run = run_train(device)
            device_actual = "cpu"
            print(f"[device] GPU OOM -> fallback CPU ({ex})", flush=True)
        else:
            raise
    t_train = time.time() - t0

    # 评估 IC + TEST 预测落盘
    t0 = time.time()
    va_pred = predict_loader(
        model, DataLoader(TensorDataset(torch.from_numpy(Xva)), batch_size=4096), device
    )
    te_pred = predict_loader(
        model, DataLoader(TensorDataset(torch.from_numpy(Xte)), batch_size=4096), device
    )
    val_ic, val_ir, val_days = daily_ic(dva, va_pred, yva)
    test_ic, test_ir, test_days = daily_ic(dte, te_pred, yte)
    q_true = assign_q_true(dte, yte)
    pred = pd.DataFrame(
        {"code": cte, "kline_time": pd.to_datetime(dte), "score": te_pred.astype(float),
         "future_ret_5d": yte.astype(float), "q_true": q_true.astype(int)}
    )
    out_pred = Path(args.out_pred)
    out_pred.parent.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(out_pred, index=False)
    t_eval = time.time() - t0

    # score 分布自检（回归是否坍缩到常数）
    n_unique = int(pd.Series(te_pred).nunique())
    score_std = float(np.std(te_pred))

    elapsed = time.time() - t_all
    metrics = {
        "arch": "mlp-90-256-64-1",
        "arch_note": "二选一中(a)MLP先跑通即锁定；(b)Tiny-1DCNN仅备选实现未启用",
        "n_params": int(n_params),
        "params_under_500k": bool(n_params < 500_000),
        "loss": "MSE", "optim": "AdamW", "lr": args.lr, "batch": args.batch,
        "epochs_run": int(epochs_run), "epochs_max": 5, "early_stop_patience": 2,
        "val_ic": val_ic, "val_ir": val_ir, "val_days": val_days,
        "test_ic": test_ic, "test_ir": test_ir, "test_days": test_days,
        "score_unique_test": n_unique, "score_std_test": score_std,
        "device_requested": dev_req, "device_actual": device_actual,
        "oom_fallback_to_cpu": oom_fallback,
        "n_train_windows": len(Xtr), "n_val_windows": len(Xva),
        "n_test_windows": len(Xte),
        "t_read_s": round(t_read, 1), "t_build_s": round(t_build, 1),
        "t_train_s": round(t_train, 1), "t_eval_s": round(t_eval, 1),
        "elapsed_s": round(elapsed, 1),
        "smoke": bool(args.smoke),
        "smoke_under_30min": bool(elapsed < 1800),
        "sample": str(args.sample), "seed": args.seed, "y_clip": Y_CLIP,
    }
    with open(args.out_metrics, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[done] val_ic={val_ic:.4f} test_ic={test_ic:.4f} "
          f"epochs={epochs_run} device={device_actual} elapsed={elapsed:.1f}s", flush=True)
    print(f"[done] pred -> {out_pred} ({len(pred):,} rows); metrics -> {args.out_metrics}", flush=True)


if __name__ == "__main__":
    main()
