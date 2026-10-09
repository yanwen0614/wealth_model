from __future__ import annotations
import json,sys
import numpy as np
REPO=r"D:\code\cnn_full_20260905\cnn"
sys.path.insert(0,REPO)
from data.labels import rank_ic
MINXS=100
OUT=r"C:\Users\yanwen\AppData\Local\Temp\opencode\unified_recalc"
FILES={"hgb_close":("logs/tree_verify/preds_p1_hgb_val.npz","logs/tree_verify/preds_p1_hgb_test.npz"),
"hgb_open":("logs/tree_verify/preds_p1_hgb_val_openopen.npz","logs/tree_verify/preds_p1_hgb_test_openopen.npz"),
"xgb_close":("logs/tree_verify/preds_p1_xgb_val.npz","logs/tree_verify/preds_p1_xgb_test.npz"),
"xgb_open":("logs/tree_verify/preds_p1_xgb_val_openopen.npz","logs/tree_verify/preds_p1_xgb_test_openopen.npz"),
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
res={"meta":{"min_xs":MINXS,"note":"H5/H10并排,不强改H,只用npz自带true_ret;2026烧掉样本只看图景;无重叠累乘","horizon":{"tree_hgb/xgb":"H5","main_A/B":"H10"}},"periods":{}}
com={}
for pi,pn in enumerate(["val2025","test2026"]):
 ds=[set(S[m][pi]) for m in S];c=sorted(set.intersection(*ds));com[pn]=c
 pr={"n_common":len(c),"full":{},"common":{}}
 for m in S:
  f=list(S[m][pi].values());cc=[S[m][pi][x] for x in c]
  f1=np.array([v[0] for v in f]);f2=np.array([v[1] for v in f]);c1=np.array([v[0] for v in cc]);c2=np.array([v[1] for v in cc])
  pr["full"][m]={"n_days":len(f),"ic_mean":float(f1.mean()),"spread_mean":float(np.nanmean(f2))}
  pr["common"][m]={"n_days":len(cc),"ic_mean":float(c1.mean()),"spread_mean":float(np.nanmean(c2))}
 res["periods"][pn]=pr
json.dump(res,open(OUT+"\\unified_ic.json","w"),indent=2,ensure_ascii=False)
json.dump({k:{"n":len(v),"start":v[0] if v else None,"end":v[-1] if v else None,"dates":v} for k,v in com.items()},open(OUT+"\\common_dates.json","w"),indent=2)
print("OK",{k:len(v) for k,v in com.items()})
for pn in ["val2025","test2026"]:
 print("==",pn,"common_n=",res["periods"][pn]["n_common"])
 for m in ["hgb_open","xgb_open","hgb_close","xgb_close","A","B"]:
  f=res["periods"][pn]["full"][m];c=res["periods"][pn]["common"][m]
  print(f"{m:9s} full[{f['n_days']:3d}] ic={f['ic_mean']:+.4f} sp={f['spread_mean']:+.4f} | com[{c['n_days']:3d}] ic={c['ic_mean']:+.4f} sp={c['spread_mean']:+.4f}")
