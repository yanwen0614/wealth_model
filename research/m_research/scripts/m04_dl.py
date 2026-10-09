"""m04: 深度时序 sweep. LSTM/GRU/TCN/Transformer 多任务(方向+幅度+波动).
H=5, EXT特征, lookback=60, expanding年WF(2019-25) purge=5. GPU串行.
用法: uv run --project . python m04_dl.py
"""
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, TensorDataset

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m_daily.parquet"
F18 = ["mom5", "mom10", "mom20", "mom60", "ma_gap20", "ma_gap40",
       "ma_gap60", "ret_std", "ret_std_ma20", "vol5_mean", "vol5_ma20",
       "breadth", "breadth_ma5", "breadth_ma20", "vol_ratio20",
       "dd60", "m_lag1", "m_ma5"]
EXT = list(dict.fromkeys(F18 + ["ret_skew", "tail_up", "tail_dn", "vol20_mean",
       "amihud_med", "vr5_med", "amt_ratio20", "breadth_ma60", "disp_ma20",
       "rv5", "rv20", "downvol20", "m_ema10", "ma_gap5", "ma_gap10",
       "dow", "month", "is_month_end"]))
L, H, EPOCHS, BS = 60, 5, 40, 256
device = "cuda" if torch.cuda.is_available() else "cpu"
class Enc(nn.Module):
    def __init__(self, f, kind):
        super().__init__(); self.kind = kind
        if kind == "lstm": self.e = nn.LSTM(f, 64, batch_first=True)
        elif kind == "gru": self.e = nn.GRU(f, 64, batch_first=True)
        elif kind == "tcn":
            self.e = nn.Sequential(nn.Conv1d(f, 64, 3, padding=1), nn.ReLU(),
                nn.Conv1d(64, 64, 3, padding=2, dilation=2), nn.ReLU(),
                nn.Conv1d(64, 64, 3, padding=4, dilation=4), nn.ReLU())
        else:
            el = nn.TransformerEncoderLayer(64, 4, 128, batch_first=True)
            self.proj = nn.Linear(f, 64); self.e = nn.TransformerEncoder(el, 2)
        self.d = nn.Linear(64, 1); self.a = nn.Linear(64, 1); self.v = nn.Linear(64, 1)
    def forward(self, x):
        if self.kind in ("lstm", "gru"): h, _ = self.e(x); h = h[:, -1]
        elif self.kind == "tcn": h = self.e(x.transpose(1, 2))[:, :, -1]
        else: h = self.e(self.proj(x))[:, -1]
        return self.d(h).squeeze(-1), self.a(h).squeeze(-1), self.v(h).squeeze(-1)
def run(kind, Xtr, ytr, dtr, vtr, Xte, seed=0):
    torch.manual_seed(seed); g = torch.Generator().manual_seed(seed)
    net = Enc(Xtr.shape[-1], kind).to(device)
    opt = torch.optim.AdamW(net.parameters(), lr=3e-4, weight_decay=1e-5)
    bce, mse = nn.BCEWithLogitsLoss(), nn.MSELoss()
    dl = DataLoader(TensorDataset(torch.tensor(Xtr, dtype=torch.float32),
        torch.tensor(ytr, dtype=torch.float32), torch.tensor(dtr, dtype=torch.float32),
        torch.tensor(vtr, dtype=torch.float32)), batch_size=BS, shuffle=True, generator=g)
    net.train()
    for _ in range(EPOCHS):
        for xb, yb, db, vb in dl:
            xb, yb, db, vb = (t.to(device) for t in (xb, yb, db, vb))
            dd, aa, vv = net(xb)
            opt.zero_grad()
            (bce(dd, db) + 0.5 * mse(aa, yb) + 0.5 * mse(vv, vb.abs())).backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        dd, aa, vv = net(torch.tensor(Xte, dtype=torch.float32).to(device))
    return dd.cpu().numpy(), aa.cpu().numpy(), vv.cpu().numpy()
daily = pd.read_parquet(D).sort_values("day").reset_index(drop=True)
lab, fwd = f"ew_up{H}", f"ew_fwd{H}"
d = daily.dropna(subset=EXT + [lab, fwd]).copy().reset_index(drop=True)
X = d[EXT].values.astype(np.float32); y = d[fwd].values.astype(np.float32)
bl = d[lab].values.astype(np.float32); days = d["day"].values
mu, sd = {}, {}
rows = []
for kind in ("lstm", "gru", "tcn", "trans"):
    P, Y, LL = [], [], []
    for yr in range(2019, 2026):
        te_m = (pd.to_datetime(days).year == yr)
        t0 = days[te_m][0]
        tr_m = days < days[np.searchsorted(np.sort(days), t0) - H]
        assert tr_m.sum() > L and te_m.sum() > 0
        m_, s_ = X[tr_m].mean(0), X[tr_m].std(0) + 1e-8
        Xs = (X - m_) / s_
        def seq(idx, Xs=Xs):
            ii = np.where(idx)[0]
            return np.stack([Xs[i - L + 1:i + 1] for i in ii if i - L + 1 >= 0]), ii[ii - L + 1 >= 0]
        Str, itr = seq(tr_m); Ste, ite = seq(te_m)
        dd, aa, _ = run(kind, Str, y[itr], bl[itr], y[itr], Ste)
        P.append(dd); Y.append(y[ite]); LL.append(bl[ite])
        print(f"{kind:5s} fold {yr}: ntr={len(itr)} nte={len(ite)}", flush=True)
    p, yy, ll = map(np.concatenate, (P, Y, LL))
    auc = roc_auc_score(ll, p)
    print(f"{kind:5s} pooled n={len(yy)} AUC={auc:.4f} "
          f"acc={float((((p>0)==(ll>0))).mean()):.4f} base={ll.mean():.3f}", flush=True)
    rows.append({"model": kind, "n": len(yy), "AUC": round(float(auc), 4),
                 "acc": round(float((((p > 0) == (ll > 0))).mean()), 4),
                 "base": round(float(ll.mean()), 4)})
pd.DataFrame(rows).to_csv(
    r"C:\Users\yanwen\AppData\Local\Temp\opencode\m_research\m04_dl.csv", index=False)
print("WROTE m04_dl.csv")
