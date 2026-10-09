"""精确优先第一批: precision-coverage / 交集 / 输家否决 / 双horizon一致. 只读, 不改仓库.

精确定义: P(文件中 true_ret > 0 | 被选中). 规则选择只看 VAL(2025), TEST(2026) 仅作图景.
用法:
  uv run --project . python precision_batch1.py --task curves --tag curves
  uv run --project . python precision_batch1.py --task pairs --tag pairs
  uv run --project . python precision_batch1.py --task veto --tag veto
产物: %TEMP%/opencode/precision/precision_<tag>.json
"""
import os
import sys
import json
import argparse
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\yanwen\AppData\Local\Temp\opencode")
from alpha_m import MODELS, load

OUTDIR = r"C:\Users\yanwen\AppData\Local\Temp\opencode\precision"

# 树模型可执行口径(open-open)追加, 仅 curves 用
EXTRA = {
    "HGB-25oo": ("logs/tree_verify/preds_p1_hgb_val_openopen.npz", 5),
    "HGB-26oo": ("logs/tree_verify/preds_p1_hgb_test_openopen.npz", 5),
    "XGB-25oo": ("logs/tree_verify/preds_p1_xgb_val_openopen.npz", 5),
    "XGB-26oo": ("logs/tree_verify/preds_p1_xgb_test_openopen.npz", 5),
}
ALL = dict(MODELS)
ALL.update(EXTRA)


def day_groups_int(d):
    order = np.argsort(d, kind="stable")
    sd = d[order]
    uniq, start = np.unique(sd, return_index=True)
    return uniq, np.split(order, start[1:])


def curves(name, ks=(1, 3, 5, 10, 20, 50, 100, 200, 500)):
    path, h = ALL[name]
    pred, true, dates, codes = load(path)
    ok = np.isfinite(pred) & np.isfinite(true)
    pred, true, dates = pred[ok], true[ok], dates[ok]
    di = dates.astype("datetime64[D]").astype(np.int64)
    total = len(pred)
    uniq, idxs = day_groups_int(di)
    out = []
    for K in ks:
        seln, up, s = 0, 0, 0.0
        for ix in idxs:
            if len(ix) < K:
                continue
            p, r = pred[ix], true[ix]
            rs = r[np.argpartition(-p, K - 1)[:K]]
            seln += K
            up += int((rs > 0).sum())
            s += float(rs.sum())
        out.append(dict(K=K, coverage=(seln / total if total else float("nan")),
                        precision=(up / seln if seln else float("nan")),
                        mean_ret=(s / seln if seln else float("nan"))))
    return dict(name=name, horizon=h, n_rows=total, n_days=len(idxs), curves=out)


def aligned_pair(nameA, nameB):
    """公共 (date, code) 宇宙内对齐. A=基准(horizon A 的 true), B=对照."""
    pa, _ = ALL[nameA]
    pb, _ = ALL[nameB]
    pra, tra, da, ca = load(pa)
    prb, trb, db, cb = load(pb)
    dfa = pd.DataFrame({"d": da.astype("datetime64[D]").astype(np.int64),
                        "code": ca, "predA": pra, "trueA": tra})
    dfb = pd.DataFrame({"d": db.astype("datetime64[D]").astype(np.int64),
                        "code": cb, "predB": prb, "trueB": trb})
    m = dfa.merge(dfb, on=["d", "code"], how="inner")
    m = m[np.isfinite(m.predA.values) & np.isfinite(m.trueA.values)
          & np.isfinite(m.predB.values) & np.isfinite(m.trueB.values)]
    return m.sort_values("d").reset_index(drop=True)


def _topn_stats(p, r, days, uniq, N):
    seln, up, s = 0, 0, 0.0
    for d in uniq:
        ix = np.where(days == d)[0]
        if len(ix) < N:
            continue
        rs = r[ix][np.argpartition(-p[ix], N - 1)[:N]]
        seln += N
        up += int((rs > 0).sum())
        s += float(rs.sum())
    return seln, (up / seln if seln else float("nan")), (s / seln if seln else float("nan"))


def intersect_analysis(nameA, nameB, Ns=(10, 50, 200)):
    m = aligned_pair(nameA, nameB)
    days = m.d.values
    uniq = np.unique(days)
    pA, rA = m.predA.values, m.trueA.values
    pB, rB = m.predB.values, m.trueB.values
    res = []
    for N in Ns:
        nA, pa_, ma_ = _topn_stats(pA, rA, days, uniq, N)
        nB, pb_, mb_ = _topn_stats(pB, rB, days, uniq, N)
        seln, upA, sA, upB, sB = 0, 0, 0.0, 0, 0.0
        for d in uniq:
            ix = np.where(days == d)[0]
            if len(ix) < N:
                continue
            inter = np.array(sorted(
                set(np.argpartition(-pA[ix], N - 1)[:N]) &
                set(np.argpartition(-pB[ix], N - 1)[:N])))
            if len(inter) == 0:
                continue
            ra, rb = rA[ix][inter], rB[ix][inter]
            seln += len(inter)
            upA += int((ra > 0).sum()); sA += float(ra.sum())
            upB += int((rb > 0).sum()); sB += float(rb.sum())
        res.append(dict(
            N=N,
            soloA=dict(precision=pa_, mean=ma_, n_sel=nA),
            soloB=dict(precision=pb_, mean=mb_, n_sel=nB),
            ixA=dict(precision=(upA / seln if seln else float("nan")),
                     mean=(sA / seln if seln else float("nan")), n_sel=seln),
            ixB=dict(precision=(upB / seln if seln else float("nan")),
                     mean=(sB / seln if seln else float("nan")), n_sel=seln)))
    return dict(pair=f"{nameA}x{nameB}", n_common=len(m), n_days=len(uniq), res=res)


def veto_analysis(nameBase, nameVeto, baseNs=(50, 200), qs=(0.1, 0.2)):
    """基准 topN 候选, 否决其中 veto 模型当日底分位. 基准=A 侧(trueA)."""
    m = aligned_pair(nameBase, nameVeto)
    days = m.d.values
    uniq = np.unique(days)
    pB, rB, pV = m.predA.values, m.trueA.values, m.predB.values
    out = []
    for N in baseNs:
        _, p0, m0 = _topn_stats(pB, rB, days, uniq, N)
        for q in qs:
            seln, up, s, vet = 0, 0, 0.0, 0
            for d in uniq:
                ix = np.where(days == d)[0]
                if len(ix) < N:
                    continue
                cand = np.argsort(-pB[ix])[:N]
                thr = np.quantile(pV[ix], q)
                keep = np.array([i for i in cand if pV[ix][i] > thr])
                vet += N - len(keep)
                if len(keep) == 0:
                    continue
                rs = rB[ix][keep]
                seln += len(keep)
                up += int((rs > 0).sum())
                s += float(rs.sum())
            out.append(dict(N=N, veto_q=q, base_precision=p0, base_mean=m0,
                            coverage=(seln / len(m) if len(m) else float("nan")),
                            precision=(up / seln if seln else float("nan")),
                            mean=(s / seln if seln else float("nan")),
                            vetoed=int(vet)))
    return dict(veto=f"{nameBase}|{nameVeto}", n_common=len(m), res=out)


PAIRS = [("B-25", "HGB-25"), ("B-26", "HGB-26"),
         ("B-25", "XGB-25"), ("B-26", "XGB-26"),
         ("A-25", "HGB-25"), ("A-26", "HGB-26"),
         ("A-25", "XGB-25"), ("A-26", "XGB-26"),
         ("B-25", "J30-25"), ("B-26", "J30-26"),
         ("A-25", "J30-25"), ("A-26", "J30-26"),
         ("B-25", "J5-25"), ("B-26", "J5-26")]

VETO_PAIRS = [("A-25", "HGB-25"), ("A-26", "HGB-26"),
              ("B-25", "HGB-25"), ("B-26", "HGB-26"),
              ("A-25", "XGB-25"), ("A-26", "XGB-26"),
              ("B-25", "XGB-25"), ("B-26", "XGB-26")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="all", choices=["curves", "pairs", "veto", "all"])
    ap.add_argument("--tag", default="all")
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    res = {}
    if a.task in ("curves", "all"):
        for name in ALL:
            d = curves(name)
            res[f"curve:{name}"] = d
            c10 = next(c for c in d["curves"] if c["K"] == 10)
            c50 = next(c for c in d["curves"] if c["K"] == 50)
            print(f"{name:9s} top10 精确={c10['precision']:.3f} 均值={c10['mean_ret']:+.5f} | "
                  f"top50 精确={c50['precision']:.3f} 均值={c50['mean_ret']:+.5f}", flush=True)
    if a.task in ("pairs", "all"):
        for x, y in PAIRS:
            d = intersect_analysis(x, y)
            res[f"pair:{x}x{y}"] = d
            for r in d["res"]:
                print(f"{x}x{y} N={r['N']:3d} soloA精确={r['soloA']['precision']:.3f} "
                      f"soloB精确={r['soloB']['precision']:.3f} "
                      f"交集A精确={r['ixA']['precision']:.3f}(n={r['ixA']['n_sel']}) "
                      f"交集B精确={r['ixB']['precision']:.3f}", flush=True)
    if a.task in ("veto", "all"):
        for x, y in VETO_PAIRS:
            d = veto_analysis(x, y)
            res[f"veto:{x}|{y}"] = d
            for r in d["res"]:
                print(f"{x}|{y} N={r['N']:3d} q={r['veto_q']:.1f} 基准精确={r['base_precision']:.3f} "
                      f"否决后={r['precision']:.3f} 均值={r['mean']:+.5f} 剔除={r['vetoed']}", flush=True)
    out = os.path.join(OUTDIR, f"precision_{a.tag}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("WROTE", out, flush=True)


if __name__ == "__main__":
    main()
