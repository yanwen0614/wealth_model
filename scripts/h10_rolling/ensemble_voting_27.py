# 27组参数投票集成：TP×TR×MH共27子策略，买票排序/≥14票卖出
# 输入：combined.npz预测+logs/ohlc_full_rolling.npz，仓库根目录运行
# 输出：r3_ens.npz(nav+days)，控制台打印NAV/ann/sharpe/mdd
# 已验证：27格点grid全跑通(r2_grid.csv)，本集成=final_combo投票部分
import sys
import itertools
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
P = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_bt\combined.npz"
O = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_risk3\r3_ens.npz"
OHLC = str(ROOT / "logs" / "ohlc_full_rolling.npz")
CAP=1e6;BC=0.00025;SC=0.00025;ST=0.00025;MC=5.0;LB=1.098;L20=1.198
def comm(v,r):
    return v*r if v*r>MC else MC
def close_pos(holds,pos,s,d,px):
    en=pos[s]["shares"]*pos[s]["entry_px"];ec=en+comm(en,BC)
    sn=pos[s]["shares"]*px;sf=comm(sn,SC)+sn*ST;pro=sn-sf
    g=px/pos[s]["entry_px"]-1.0;n=(pro-ec)/ec
    holds.append((pos[s]["entry_date"],d,s,pos[s]["weight"],pos[s]["entry_px"],px,g,n))
    return pro/CAP
def metrics(nav):
    nav=np.asarray(nav,float);r=nav[1:]/nav[:-1]-1.0;n=len(r);sd=r.std()
    ann=float(nav[-1]**(252.0/n)-1.0) if n else 0.0
    sh=float(r.mean()/sd*(252.0**0.5)) if sd>0 else 0.0
    pk=np.maximum.accumulate(nav);mdd=float((1.0-nav/pk).max()) if n else 0.0
    return ann,sh,mdd,float(nav[-1])
def load():
    z=np.load(P,allow_pickle=True)
    E=np.asarray(z["exp_ret"],float);C=np.asarray(z["codes"]).astype(str)
    D=z["dates"].astype("datetime64[D]")
    o=np.load(OHLC,allow_pickle=True)
    OC=np.asarray(o["codes"]).astype(str);OD=o["dates"].astype("datetime64[D]")
    m=(OD>=D.min())&(OD<=np.datetime64("2025-12-31"))
    OD=OD[m];OM=np.asarray(o["open_m"],float)[:,m];CM=np.asarray(o["close_m"],float)[:,m]
    RT=np.where(np.isfinite(CM[:,1:]),CM[:,1:]/np.where(CM[:,:-1]==0,np.nan,CM[:,:-1])-1,np.nan)
    MR=np.nanmean(RT,axis=0);MR=np.where(np.isfinite(MR),MR,0.0)
    IX=np.cumprod(np.concatenate([[1.0],1+MR]))
    MA=np.concatenate([np.full(39,np.nan),np.convolve(IX,np.ones(40)/40,"valid")])
    ON=np.where(np.isnan(MA),True,IX>MA);OFF=set(OD[~ON].astype(str))
    E=E.copy();E[np.isin(D.astype(str),list(OFF))]=-np.inf
    return E,C,D,OC,OD,OM,CM,{s:i for i,s in enumerate(OC)}
def gstep(st,TP,TR,MH,ol,em,day,i,OM,CM,ROW,OD):
    pos=st["pos"];cash=st["cash"];buys=[]
    for s,p in pos.items():
        px=OM[ROW[s],i]
        if not np.isnan(px):p["price"]=px
    sell=set(s for s in pos if em.get(s) is not None and em[s]<=0.0)
    for s in list(pos):
        p=pos[s];px=OM[ROW[s],i]
        if np.isnan(px):px=p["price"]
        pk=max(p["peak"],px);p["peak"]=pk
        if (pk/p["entry_px"]-1.0)>=TP and (pk-px)/pk>=TR:sell.add(s)
        elif i-p["ei"]>=MH:sell.add(s)
    for s in list(sell & set(pos)):
        px=OM[ROW[s],i]
        if np.isnan(px):px=pos[s]["price"]
        cash+=close_pos(st["holds"],pos,s,day,px);del pos[s]
    npre=cash+sum(p["shares"]*p["price"] for p in pos.values())/CAP
    if i<len(OD)-1 and npre>0:
        slots=20-len(pos)
        for k in range(min(20,len(ol))):
            if slots<=0:break
            s=ol[k]
            if s in pos or em[s]<0.02:continue
            r_=ROW.get(s)
            if r_ is None:continue
            px=OM[r_,i];pc=CM[r_,i-1]
            if np.isnan(px) or np.isnan(pc):continue
            if px>=pc*(L20 if s[:3] in ("300","688") else LB):continue
            b=min((npre/20)*CAP,cash*CAP)
            if b<=5.0:continue
            bs=5.0*(1.0+BC)/BC
            sh=b/(px*(1.0+BC)) if b>=bs else (b-5.0)/px
            bn=sh*px;cash-=(bn+comm(bn,BC))/CAP
            pos[s]={"shares":sh,"price":px,"entry_date":day,"entry_px":px,"weight":0.05,"peak":px,"ei":i}
            slots-=1;buys.append(s)
    st["cash"]=cash
    return buys
def main():
    E,C0,D0,OC,OD,OM,CM,ROW=load()
    PR=list(itertools.product([0.20,0.30,0.40],[0.08,0.12,0.15],[60,90,120]))
    TPA=np.array([p[0] for p in PR]);TRA=np.array([p[1] for p in PR]);MHA=np.array([p[2] for p in PR])
    SH=[{"pos":{},"cash":1.0,"holds":[]} for _ in PR]
    EP,EC,EN,EH,prev={},1.0,np.ones(len(OD)),[],None
    for i,day in enumerate(OD):
        for s,p in EP.items():
            px=OM[ROW[s],i]
            if not np.isnan(px):p["price"]=px;p["peaks"]=np.maximum(p["peaks"],px)
        if i>0 and prev is not None:
            ol,rm,em=prev;votes={}
            for gi,(a,b,cc) in enumerate(PR):
                for s in gstep(SH[gi],a,b,cc,ol,em,day,i,OM,CM,ROW,OD):votes[s]=votes.get(s,0)+1
            sell=set()
            for s in list(EP):
                p=EP[s];px=OM[ROW[s],i]
                if np.isnan(px):px=p["price"]
                e0=em.get(s)
                if e0 is not None and e0<=0.0:sell.add(s);continue
                arm=p["peaks"]/p["entry_px"]-1.0>=TPA
                hit=(p["peaks"]-px)/p["peaks"]>=TRA;mx=(i-p["ei"])>=MHA
                if int(((arm & hit)|mx).sum())>=14:sell.add(s)
            for s in list(sell & set(EP)):
                px=OM[ROW[s],i]
                if np.isnan(px):px=EP[s]["price"]
                EC+=close_pos(EH,EP,s,day,px);del EP[s]
            npre=EC+sum(p["shares"]*p["price"] for p in EP.values())/CAP
            if i<len(OD)-1 and npre>0:
                slots=20-len(EP);rk={s:k for k,s in enumerate(ol)}
                cand=sorted(votes,key=lambda s:(-votes[s],rk.get(s,99999)))
                for s in cand:
                    if slots<=0:break
                    if s in EP or em.get(s,-9)<0.02:continue
                    r_=ROW.get(s)
                    if r_ is None:continue
                    px=OM[r_,i];pc=CM[r_,i-1]
                    if np.isnan(px) or np.isnan(pc):continue
                    if px>=pc*(L20 if s[:3] in ("300","688") else LB):continue
                    b=min((npre/20)*CAP,EC*CAP)
                    if b<=5.0:continue
                    bs=5.0*(1.0+BC)/BC
                    sh=b/(px*(1.0+BC)) if b>=bs else (b-5.0)/px
                    bn=sh*px;EC-=(bn+comm(bn,BC))/CAP
                    EP[s]={"shares":sh,"price":px,"entry_date":day,"entry_px":px,"weight":0.05,"peaks":np.full(27,px),"ei":i}
                    slots-=1
        if i==len(OD)-1 and EP:
            for s in list(EP):
                px=OM[ROW[s],i]
                if np.isnan(px):px=EP[s]["price"]
                EC+=close_pos(EH,EP,s,day,px)
            EP={}
        EN[i]=EC+sum(p["shares"]*p["price"] for p in EP.values())/CAP
        mm=D0==day
        if mm.any():
            ee=E[mm];cc=C0[mm];ix=np.argsort(-ee,kind="stable")
            ol=[str(cc[j]) for j in ix];em={ol[k]:float(ee[ix[k]]) for k in range(len(ol))}
            prev=(ol,{s:k+1 for k,s in enumerate(ol)},em)
    ann,sh,mdd,last=metrics(EN)
    print(f"ENS NAV={last:.4f} ann={ann:.4f} sharpe={sh:.4f} mdd={mdd:.4f} n={len(EH)}",flush=True)
    np.savez_compressed(O,nav=EN,days=OD)
if __name__=="__main__":
    main()
