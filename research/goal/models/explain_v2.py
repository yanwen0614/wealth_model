"""v2 HGB importance实算: 与train_realizable.py完全同构重训 + 双口径重要性.
口径:
 (a) HGB内置: 注意 HistGradientBoostingRegressor无feature_importances_ API (已实测AttributeError),
     此处用内部TreePredictor.nodes gain按feature_idx加总归一化, 作为最忠实的内置增益口径.
 (b) VAL 20万抽样permutation: baseline为截面IC(与cross_section_ic一致), 每次permute一列后重predict重算IC, importance=baseline-IC_permuted, n_repeats=3, rng42.
scaler只load绝不fit. 配置与metrics_v2.json selected_params对照打印.
"""
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "models"))
import pyarrow.parquet as pq
from prep import split_frame
from train_realizable import (
    HAND_COLS,
    batched_predict,
    build_split_samples,
    cross_section_ic,
    fit_hgb,
    sample_weights,
)
from vendor_scaler import PerCodeGroupedScaler

SCALER_P = ROOT/"artifacts"/"scaler.pkl"
FULL_P = ROOT/"data"/"train_data.parquet"
METRICS_P = ROOT/"artifacts"/"opt_model"/"metrics_v2.json"
MODEL_OUT = ROOT/"artifacts"/"opt_model"/"model_v2.pkl"
IMP_JSON = ROOT/"artifacts"/"opt_model"/"importance_v2.json"
TOP20_CSV = ROOT/"artifacts"/"opt_model"/"top20.csv"

EXPECTED = {"loss":"squared_error","max_iter":150,"max_leaf_nodes":63,"early_stopping":True,"validation_fraction":0.1,"random_state":42}

def main():
    t0=time.time()
    with open(METRICS_P) as f:
        m0=json.load(f)
    sel=m0["selected_params"]
    print("[对照] metrics_v2.json selected_params:", json.dumps(sel, ensure_ascii=False))
    print("[对照] 本次预期配置:", json.dumps(EXPECTED, ensure_ascii=False))
    print("[对照] 一致:", sel==EXPECTED, "| 历史VAL IC(150候选)=", m0["candidates"]["150"]["val_ic"], "| val_ic=", m0["val_ic"])
    assert sel==EXPECTED, "selected_params不一致, 停止"

    scaler=PerCodeGroupedScaler.load(str(SCALER_P))  # 只load
    feature_cols=list(scaler.feature_cols)
    feat_out=list(scaler.feature_cols_out)+HAND_COLS
    assert len(feat_out)==49, len(feat_out)
    print(f"[feat] in={len(feature_cols)} out={len(feat_out)}")

    use_cols=list(dict.fromkeys(["code","kline_time","close","open","is_trading"]+feature_cols))
    df=pq.read_table(str(FULL_P), columns=use_cols).to_pandas()
    df["kline_time"]=pd.to_datetime(df["kline_time"])
    print(f"[read] {len(df):,} rows codes={df['code'].nunique()}")
    splits=split_frame(df); del df

    Xtr,ytr,_,_=build_split_samples(splits["TRAIN"], scaler, feature_cols, "realizable")
    del splits["TRAIN"]
    print(f"[TRAIN] {Xtr.shape}")
    Xva,yva,_,mva=build_split_samples(splits["VAL"], scaler, feature_cols, "realizable")
    del splits["VAL"]
    print(f"[VAL] {Xva.shape}")
    print(f"[VAL] y mean={float(yva.mean()):.6f} std={float(yva.std()):.6f}")

    wtr=sample_weights(ytr)
    # 候选复核: TRAIN-only max_iter=150
    cand,secs=fit_hgb(Xtr,ytr,wtr,150,63)
    print(f"[cand150] fit {secs:.1f}s")
    sc=batched_predict(cand,Xva)
    dv=pd.DataFrame({"kline_time":mva["kline_time"].values,"score":sc,"realizable_ret":yva.astype(np.float64)})
    ic,ir,nd,_=cross_section_ic(dv,ret_col="realizable_ret")
    print(f"[cand150] VAL IC={ic:.6f} IR={ir:.4f} days={nd} (历史0.061042)")
    diff=abs(ic-0.06104204735470689)
    print(f"[gate] |IC-0.061042|={diff:.6f} (阈值0.005, 任务书0.0610)")
    if diff>0.005:
        print("[GATE FAIL] VAL IC偏差>0.005, 停止排查, 不写模型")
        with open(ROOT/"artifacts"/"opt_model"/"importance_run.log","w") as f:
            f.write(f"GATE FAIL ic={ic} diff={diff}\n")
        sys.exit(2)
    del cand,sc,dv

    # 最终 TRAIN+VAL 合并重训
    Xf=np.concatenate([Xtr,Xva],axis=0); yf=np.concatenate([ytr,yva],axis=0)
    del Xtr,ytr,Xva
    wf=sample_weights(yf)
    print(f"[final] n={len(yf):,} fit start...")
    final,fsecs=fit_hgb(Xf,yf,wf,150,63)
    print(f"[final] done {fsecs:.1f}s")
    del Xf,yf,wf
    # 保存
    MODEL_OUT.parent.mkdir(parents=True,exist_ok=True)
    with open(MODEL_OUT,"wb") as f:
        pickle.dump({"model":final,"feature_names":feat_out,"selected_params":EXPECTED,
                     "val_ic_cand150":float(ic),"fit_final_secs":float(fsecs)},f)
    print(f"[save] {MODEL_OUT} {MODEL_OUT.stat().st_size/1e6:.1f}MB")
    print("[api-check] hasattr feature_importances_:", hasattr(final,"feature_importances_"))

    # (a) 内置gain: TreePredictor.nodes gain加总
    nF=len(feat_out)
    gain=np.zeros(nF)
    split_cnt=np.zeros(nF,dtype=int)
    n_trees=0
    for it in final._predictors:
        for p in it:
            n_trees+=1
            nodes=p.nodes
            for ndrow in nodes:
                if not ndrow["is_leaf"]:
                    fi=int(ndrow["feature_idx"])
                    if 0<=fi<nF:
                        gain[fi]+=float(ndrow["gain"])
                        split_cnt[fi]+=1
    tot=gain.sum()
    gain_norm=(gain/tot).tolist() if tot>0 else [0.0]*nF
    print(f"[gain] trees={n_trees} total_gain={tot:.3e} top_idx={int(np.argmax(gain))}({feat_out[int(np.argmax(gain))]})")

    # (b) VAL 20万 permutation, Spearman截面IC口径
    # 需重建VAL X,y,meta (上面Xva已del yva? yva还在, Xva已拼入Xf; 重建以省内存: 重新build VAL)
    # 为省时间, 我们在final fit前已删Xva; 这里重新从splits? splits VAL已del. 重新读VAL段再build.
    print("[perm] 重读VAL段构建20万样本...")
    df2=pq.read_table(str(FULL_P), columns=use_cols).to_pandas()
    df2["kline_time"]=pd.to_datetime(df2["kline_time"])
    sp2=split_frame(df2); del df2
    Xv2,yv2,_,mv2=build_split_samples(sp2["VAL"], scaler, feature_cols, "realizable")
    del sp2
    print(f"[perm] VAL rebuild {Xv2.shape}")
    rng=np.random.default_rng(42)
    N=len(yv2); S=200_000
    idx=rng.choice(N,S,replace=False) if N>S else np.arange(N)
    Xs=Xv2[idx]; ys=yv2[idx].astype(np.float64); ts=mv2["kline_time"].values[idx]
    del Xv2,yv2,mv2
    base_sc=batched_predict(final,Xs)
    base_df=pd.DataFrame({"kline_time":ts,"score":base_sc,"realizable_ret":ys})
    base_ic,_,base_nd,_=cross_section_ic(base_df,ret_col="realizable_ret")
    print(f"[perm] baseline IC_20w={base_ic:.6f} days={base_nd} N={len(ys)}")
    rng2=np.random.default_rng(42)
    perm_mean=[]; perm_std=[]
    # 预生成每列每repeat的置换索引? 为可复现, 对每列每repeat用rng2.permutation(S)
    for j in range(nF):
        drops=[]
        for r in range(3):
            perm=rng2.permutation(S)
            Xp=Xs.copy()
            Xp[:,j]=Xs[perm,j]
            scp=batched_predict(final,Xp)
            dfp=pd.DataFrame({"kline_time":ts,"score":scp,"realizable_ret":ys})
            icp,_,_,_=cross_section_ic(dfp,ret_col="realizable_ret")
            drops.append(float(base_ic-icp))
            del Xp,scp,dfp
        perm_mean.append(float(np.mean(drops))); perm_std.append(float(np.std(drops,ddof=1) if len(drops)>1 else 0.0))
        if (j+1)%10==0: print(f"[perm] {j+1}/{nF} ... {feat_out[j]} drop={perm_mean[-1]:.6f}")
    # 存json/csv
    out={"feature_names":feat_out,
         "config":{"max_iter":150,"scaler":"load-only artifacts/scaler.pkl","val_sample":int(S),"random_state":42,"n_repeats":3,
                   "scoring":"cross_section_ic(Spearman截面IC, 与train_realizable.cross_section_ic一致)","baseline_ic_20w":float(base_ic),
                   "val_ic_cand150_full":float(ic),"gate_ref":0.06104204735470689,
                   "note_a":"HistGradientBoostingRegressor无feature_importances_属性(已实测); (a)为内部TreePredictor.nodes gain按feature_idx加总归一化",
                   "note_b":"每次permutate一列后在VAL 20万样本上重predict重算截面IC, importance=baseline_IC-IC_permuted, 3次平均"},
         "hgb_gain_raw":gain.tolist(),"hgb_gain_norm":gain_norm,"split_count":split_cnt.tolist(),
         "perm_baseline_ic":float(base_ic),"perm_drop_mean":perm_mean,"perm_drop_std":perm_std}
    with open(IMP_JSON,"w") as f: json.dump(out,f,indent=2)
    print(f"[save] {IMP_JSON}")
    # top20: 按perm_drop_mean排序? 双口径各top? 此处按perm排top20, 附gain
    order=np.argsort(np.array(perm_mean))[::-1]
    import csv
    with open(TOP20_CSV,"w",newline="") as f:
        w=csv.writer(f)
        w.writerow(["rank","feature","group","perm_drop_mean","perm_drop_std","gain_norm","gain_raw","split_count"])
        for rk,i in enumerate(order[:20],1):
            w.writerow([rk,feat_out[i],group_of(feat_out[i]),f"{perm_mean[i]:.6f}",f"{perm_std[i]:.6f}",f"{gain_norm[i]:.6f}",f"{gain[i]:.3f}",int(split_cnt[i])])
    print(f"[save] {TOP20_CSV}")
    print(f"[done] total {time.time()-t0:.0f}s")

def group_of(c):
    G1={"open","high","low","ma_5","ma_10","ma_20","ma_60","ema_12","ema_26","sar","trend_duokong","trend_shortline"}
    G3={"volatility_5d","volatility_10d","volatility_20d","std_5","std_10","std_20","atr"}
    G4={"volume_ratio_5d","volume_ratio_10d","amihud"}
    G5={"macd","dmi","adx","boll","kelch","trend_duokong_dev"}
    G8={"gross_margin","net_margin","roe","roa","debt_to_equity"}
    G9={"margin_balance_ratio","margin_buy_ratio","margin_net_buy_ratio","margin_balance_chg_5d","short_balance_ratio","short_sell_vol_ratio"}
    if c in G1: return "G1价格相对"
    if c in G3: return "G3波动"
    if c in G4: return "G4量能"
    if c in G5: return "G5技术"
    if c in G8: return "G8质量"
    if c in G9: return "G9两融"
    if c.endswith("_mask"): return "G9mask"
    if c in ("mean_5","mean_20","vol_20","ret_20"): return "手工统计"
    return "?"
if __name__=="__main__":
    main()
