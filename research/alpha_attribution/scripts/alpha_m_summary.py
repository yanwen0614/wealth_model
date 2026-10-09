"""汇总 alpha_m 三组 JSON 为统一对照表. 只读."""
import json
import os

D = r"C:\Users\yanwen\AppData\Local\Temp\opencode\alpha_m"
FILES = ["alpha_m_main.json", "alpha_m_jkx.json", "alpha_m_tree_fixed.json"]
ORDER = ["A-25", "A-26", "B-25", "B-26", "J30-25", "J30-26", "J5-25", "J5-26",
         "HGB-25", "HGB-26", "XGB-25", "XGB-26",
         "HGBroll-25", "HGBroll-26", "XGBroll-25", "XGBroll-26"]

res = {}
for f in FILES:
    p = os.path.join(D, f)
    if os.path.exists(p):
        res.update(json.load(open(p, encoding="utf-8")))

# topn 索引: 0=N10重叠 1=N10非重叠 2=N50重叠 3=N50非重叠 4=N200重叠 5=N200非重叠
cols = ("model,h,n,within,market,std_pred,corr_pm_m,"
        "t10_ovl_port,t10_ovl_m_t,t10_ovl_alpha_t,t10_ovl_share,t10_ovl_win,"
        "t200_ovl_port,t200_ovl_m_t,t200_ovl_alpha_t,t200_ovl_share,t200_ovl_win,"
        "t10_non_alpha_t,t10_non_share,t200_non_alpha_t,t200_non_share")
print(cols)
for k in ORDER:
    if k not in res:
        print(f"{k},MISSING")
        continue
    d = res[k]
    t = d["topn"]

    def g(i, f):
        return t[i][f]

    row = [k, str(d["horizon"]), str(d["n_rows"]),
           f"{d['within_pooled']:.4f}", f"{d['market_pooled']:.4f}",
           f"{d['std_pred_mean']:.5f}", f"{d['corr_predmean_m']:+.3f}",
           f"{g(0,'port'):+.5f}", f"{g(0,'m'):+.5f}({g(0,'m_t'):+.2f})",
           f"{g(0,'alpha'):+.5f}({g(0,'alpha_t'):+.2f})", f"{g(0,'m_share'):+.3f}",
           f"{g(0,'alpha_win'):.3f}",
           f"{g(4,'port'):+.5f}", f"{g(4,'m'):+.5f}({g(4,'m_t'):+.2f})",
           f"{g(4,'alpha'):+.5f}({g(4,'alpha_t'):+.2f})", f"{g(4,'m_share'):+.3f}",
           f"{g(4,'alpha_win'):.3f}",
           f"{g(1,'alpha_t'):+.2f}", f"{g(1,'m_share'):+.3f}",
           f"{g(5,'alpha_t'):+.2f}", f"{g(5,'m_share'):+.3f}"]
    print(",".join(row))
