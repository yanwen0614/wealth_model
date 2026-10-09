from __future__ import annotations
import json,sys
import numpy as np
REPO=r"D:\code\cnn_full_20260905\cnn"
sys.path.insert(0,REPO)
from data.labels import rank_ic
MINXS=100;B=2000;BL=20;SEED=42
OUT=r"C:\Users\yanwen\AppData\Local\Temp\opencode\unified_recalc"
FILES={"hgb_open":("logs/tree_verify/preds_p1_hgb_val_openopen.npz","logs/tree_verify/preds_p1_hgb_test_openopen.npz"),
"xgb_open":("logs/tree_verify/preds_p1_xgb_val_openopen.npz","logs/tree_verify/preds_p1_xgb_test_openopen.npz"),
"hgb_close":("logs/tree_verify/preds_p1_hgb_val.npz","logs/tree_verify/preds_p1_hgb_test.npz"),
"xgb_close":("logs/tree_verify/preds_p1_xgb_val.npz","logs/tree_verify/preds_p1_xgb_test.npz"),
"A":("logs/preds_fullA_2025.npz","logs/preds_fullA_2026.npz"),
"B":("logs/preds_fullB_2025.npz","logs/preds_fullB_2026.npz")}
def load(p):
 z=np.load(REPO+"\\"+p);e=np.asarray(z["exp_ret"],float);r=np.asarray(z["true_ret"],float);d=np.asarray(z["dates"]).astype("datetime64[D]");m=np.isfinite(e)&np.isfinite(r);return e[m],r[m],d[m]
def daily(e,r,d):
 o={};
 for x in np.unique(d):
  m=d==x
  if int(m.sum())<MINXS:continue
  ee,rr=e[m],r[m];q9,q1=np.quantile(ee,(0.9,0.1));o[str(x)]=(rank_ic(ee,rr),float(rr[ee>=q9].mean())-float(rr[ee<=q1].mean()))
 return o
S={m:[daily(*load(p)) for p in v] for m,v in FILES.items()}
COM=json.load(open(OUT+"\\common_dates.json"))
PAIRS=[("hgb_open","A"),("hgb_open","B"),("xgb_open","A"),("xgb_open","B")]
def blk(n,g):
 return np.concatenate([(g.integers(0,n)+np.arange(BL))%n for _ in range((n+BL-1)//BL)])[:n]
def boot_diff(a,b):
 d=np.asarray(a,float)-np.asarray(b,float);n=len(d);g=np.random.default_rng(SEED);X=np.empty(B)
 for i in range(B):X[i]=d[blk(n,g)].mean()
 return float(d.mean()),float(np.quantile(X,0.025)),float(np.quantile(X,0.975)),float((X>0).mean())
def boot_mean(a):
 a=np.asarray(a,float);n=len(a);g=np.random.default_rng(SEED+1);X=np.empty(B)
 for i in range(B):X[i]=a[blk(n,g)].mean()
 return float(a.mean()),float(np.quantile(X,0.025)),float(np.quantile(X,0.975))
ric={};rsp={}
for pn,pi in (("val2025",0),("test2026",1)):
 c=COM[pn]["dates"];ric[pn]=[];rsp[pn]=[]
 for t,m in PAIRS:
  ti=np.array([S[t][pi][x][0] for x in c]);mi=np.array([S[m][pi][x][0] for x in c]);a,lo,hi,p=boot_diff(ti,mi);ric[pn].append({"pair":f"{t}-{m}","mean":a,"lo":lo,"hi":hi,"P>0":p,"n":len(c)})
  ts=np.array([S[t][pi][x][1] for x in c]);ms=np.array([S[m][pi][x][1] for x in c]);a,lo,hi,p=boot_diff(ts,ms);rsp[pn].append({"pair":f"{t}-{m}_spread","mean":a,"lo":lo,"hi":hi,"P>0":p,"n":len(c)})
 for m in ["hgb_open","xgb_open","A","B"]:
  s=np.array([S[m][pi][x][1] for x in c]);a,lo,hi=boot_mean(s);rsp[pn].append({"pair":m+"_spread_lvl","mean":a,"lo":lo,"hi":hi,"P>0":None,"n":len(c)})
json.dump({"cfg":"block20_B2000_seed42","periods":ric},open(OUT+"\\boot_ic.json","w"),indent=2)
json.dump({"cfg":"block20_B2000_seed42","periods":rsp},open(OUT+"\\boot_spread.json","w"),indent=2)
open(OUT+"\\boot_ic.csv","w").write("period,pair,mean,lo,hi,Pgt0,n\n"+"\n".join(f"{p},{r['pair']},{r['mean']:.5f},{r['lo']:.5f},{r['hi']:.5f},{r['P>0']:.4f},{r['n']}" for p in ric for r in ric[p]))
open(OUT+"\\boot_spread.csv","w").write("period,pair,mean,lo,hi,Pgt0,n\n"+"\n".join(f"{p},{r['pair']},{r['mean']:.5f},{r['lo']:.5f},{r['hi']:.5f},{r['P>0']},{r['n']}" for p in rsp for r in rsp[p]))
print("OK boot done")
for p in ric:
 for r in ric[p]:print(p,r["pair"],f"diff={r['mean']:+.4f} CI[{r['lo']:+.4f},{r['hi']:+.4f}] P={r['P>0']:.4f}")
