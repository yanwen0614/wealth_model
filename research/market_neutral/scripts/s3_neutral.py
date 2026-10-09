from __future__ import annotations
import json,sys
import numpy as np
REPO=r"D:\code\cnn_full_20260905\cnn"
sys.path.insert(0,REPO)
from data.labels import rank_ic
MINXS=100
OUT=r"C:\Users\yanwen\AppData\Local\Temp\opencode\market_neutral"
FILES={"hgb_open":"logs/tree_verify/preds_p1_hgb_test_openopen.npz","hgb_open_v":"logs/tree_verify/preds_p1_hgb_val_openopen.npz",
"xgb_open":"logs/tree_verify/preds_p1_xgb_test_openopen.npz","xgb_open_v":"logs/tree_verify/preds_p1_xgb_val_openopen.npz",
"A":"logs/preds_fullA_2026.npz","A_v":"logs/preds_fullA_2025.npz",
"B":"logs/preds_fullB_2026.npz","B_v":"logs/preds_fullB_2025.npz"}
def load(p):
 z=np.load(REPO+"\\"+p);e=np.asarray(z["exp_ret"],float);r=np.asarray(z["true_ret"],float);d=np.asarray(z["dates"]).astype("datetime64[D]");m=np.isfinite(e)&np.isfinite(r);return e[m],r[m],d[m]
LS={};AT={}
for m,p in FILES.items():
 e,r,d=load(p);D={};M=[];I=[]
 for x in np.unique(d):
  k=d==x
  if int(k.sum())<MINXS:continue
  ee,rr=e[k],r[k];mt=float(rr.mean());al=rr-mt;o=np.argsort(-ee)
  dd={"m":mt,"xs":float(rr.std())}
  for N in (10,100):
   n=min(N,len(o));dd[N]=(float(rr[o[:n]].mean()-rr[o[-n:]].mean()),float(al[o[:n]].mean()-al[o[-n:]].mean()))
  D[str(x)]=dd;M.append(mt);I.append((rank_ic(ee,rr),rank_ic(ee,al)))
 Ia=np.array([a for a,b in I]);Ib=np.array([b for a,b in I]);mx=float(np.max(np.abs(Ia-Ib)))
 AT[m]={"n_days":len(D),"ic_identity_maxdiff":mx,"mean_abs_mt":float(np.mean(np.abs(M))),"mean_xs_std":float(np.mean([D[k]["xs"] for k in D]))}
 for N in (10,100):
  v=np.array([D[k][N][0] for k in D]);w=np.array([D[k][N][1] for k in D])
  LS[f"{m}_N{N}"]={"n_days":len(D),"ls_mean":float(v.mean()),"ls_std":float(v.std(ddof=1)),"pos_rate":float((v>0).mean()),"ls_alpha_mean":float(w.mean()),"maxabsdiff_ls_alpha":float(np.max(np.abs(v-w)))}
MO="paper-only:long-short topN-bottomN等权,true_ret计价,m_t剥离;不计费;不是回测收益;run_backtest仅long-only故无空头引擎对照"
json.dump({"meta":MO,"rows":LS},open(OUT+"\\ls_spread.json","w"),indent=2,ensure_ascii=False)
json.dump({"meta":MO+";波动IC显著不 reinterpret为方向可用","rows":AT},open(OUT+"\\alpha_attr.json","w"),indent=2,ensure_ascii=False)
print("OK ls/attr")
for k in sorted(LS):print(k,f"ls={LS[k]['ls_mean']:+.4f} pos={LS[k]['pos_rate']:.2f} maxdiff={LS[k]['maxabsdiff_ls_alpha']:.1e}")
for k in sorted(AT):print(k,f"ICid_maxdiff={AT[k]['ic_identity_maxdiff']:.1e} |mt|={AT[k]['mean_abs_mt']:.4f}")
