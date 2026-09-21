# 回撤减半风控：峰值回撤超10%后新开仓减半，直至收复新高
# 输入：combined.npz预测+logs/ohlc_full_rolling.npz，仓库根目录运行
# 输出：dd10.npz(nav+H+days)，控制台打印NAV/ann/sharpe/mdd/tradewin
# 已验证：与run_risk同口径dd10行可复现，相对base显著降mdd(ann≈0.24/mdd≈0.20)
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
P = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_bt\combined.npz"
O = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_risk1\dd10.npz"
OHLC = str(ROOT / "logs" / "ohlc_full_rolling.npz")
BR=SR=TR=0.00025;MC=5.0;CAP=1e6
def _c(v,r):
    return v*r if v*r>MC else MC
def _x(H,p,s,d,px,cap,w):
    sh,_,ex,ed,ei,pk,am,sg=p[s]
    ec=sh*ex+_c(sh*ex,BR);sn=sh*px
    pr=sn-_c(sn,SR)-sn*TR
    H.append((ed,d,s,w,ex,px,px/ex-1.0,(pr-ec)/ec))
    return pr/cap
def do_buy(pos,cash,pre,ol,em,row,om,cm,i,dd,size,sc):
    slots=size-len(pos)
    for k in range(min(size,len(ol))):
        if slots<=0:break
        s=ol[k]
        if s in pos or em[s]<0.02:continue
        r=row.get(s)
        if r is None:continue
        px=om[r,i];pc=cm[r,i-1]
        if not (np.isfinite(px) and np.isfinite(pc)):continue
        if px>=pc*(1.198 if s[:3] in ("300","688") else 1.098):continue
        bg=min(pre/size*sc*CAP,cash*CAP)
        if bg<=MC:continue
        bs=MC*(1+BR)/BR
        sh=bg/(px*(1+BR)) if bg>=bs else (bg-MC)/px
        bn=sh*px;cash-=(bn+_c(bn,BR))/CAP
        pos[s]=[sh,px,px,dd,i,px,False,False];slots-=1
    return cash
def load():
    z=np.load(P,allow_pickle=True)
    e=np.asarray(z["exp_ret"],float);c=np.asarray(z["codes"]).astype(str)
    d=z["dates"].astype("datetime64[D]")
    o=np.load(OHLC,allow_pickle=True)
    oc=np.asarray(o["codes"]).astype(str);od=o["dates"].astype("datetime64[D]")
    m=(od>=d.min())&(od<=np.datetime64("2025-12-31"))
    od=od[m];om=np.asarray(o["open_m"],float)[:,m];cm=np.asarray(o["close_m"],float)[:,m]
    rt=np.where(np.isfinite(cm[:,1:]),cm[:,1:]/np.where(cm[:,:-1]==0,np.nan,cm[:,:-1])-1,np.nan)
    mr=np.nanmean(rt,axis=0);mr=np.where(np.isfinite(mr),mr,0.0)
    ix=np.cumprod(np.concatenate([[1.0],1+mr]))
    ma=np.concatenate([np.full(39,np.nan),np.convolve(ix,np.ones(40)/40,"valid")])
    on=np.where(np.isnan(ma),True,ix>ma)
    e2=e.copy();e2[np.isin(d.astype(str),list(set(od[~on].astype(str))))]=-np.inf
    return e2,c,d,oc,od,om,cm
def main():
    e,c,d,oc,od,om,cm=load()
    row={s:i for i,s in enumerate(oc)};n=len(od)
    pos,H,cash,nav,cr={},[],1.0,np.ones(n),[]
    prev,pk,half=None,1.0,False
    for i,dd in enumerate(od):
        for s in pos:
            q=om[row[s],i]
            if np.isfinite(q):pos[s][1]=q
        if i>0 and prev is not None:
            ol,_,em=prev
            for s in [x for x in pos if em.get(x) is not None and em[x]<=0.0]+[x for x in pos if pos[x][7]]:
                if s not in pos:continue
                q=om[row[s],i];q=pos[s][1] if not np.isfinite(q) else q
                cash+=_x(H,pos,s,dd,q,CAP,1.0/20);del pos[s]
            pre=cash+sum(p[0]*p[1] for p in pos.values())/CAP
            pk=max(pk,nav[i-1])
            dw=(pk-pre)/pk if pk>0 else 0.0
            half=True if dw>0.10 else (False if pre>=pk else half)
            if i<n-1 and pre>0:
                cash=do_buy(pos,cash,pre,ol,em,row,om,cm,i,dd,20,0.5 if half else 1.0)
        if i==n-1 and pos:
            for s in list(pos):
                q=om[row[s],i]
                if not np.isfinite(q):q=pos[s][1]
                cash+=_x(H,pos,s,dd,q,CAP,1.0/20)
            pos={}
        nav[i]=cash+sum(p[0]*p[1] for p in pos.values())/CAP
        cr.append(cash/nav[i] if nav[i]>0 else 1.0)
        m=d==dd
        if m.any():
            ee,cc=e[m],c[m];o2=np.argsort(-ee,kind="stable")
            ol=[str(cc[j]) for j in o2]
            prev=(ol,{},{ol[k]:float(ee[o2[k]]) for k in range(len(ol))})
        for s in pos:
            p=pos[s];cc=cm[row[s],i]
            if np.isfinite(cc):
                p[5]=max(p[5],cc);p[6]=p[6] or p[5]/p[2]-1.0>=0.30
                p[7]=p[7] or (p[6] and (p[5]-cc)/p[5]>0.12)
            p[7]=p[7] or (i+1-p[4])>90
    dt=np.dtype([("entry_date","datetime64[D]"),("exit_date","datetime64[D]"),("code","U16"),("weight","f8"),("open_t1","f8"),("open_t6","f8"),("ret_gross","f8"),("ret_net","f8")])
    Ha=np.array(H,dtype=dt) if H else np.array([],dtype=dt)
    r=nav[1:]/nav[:-1]-1.0;nn=len(r);sd=r.std()
    ann=float(nav[-1]**(252.0/nn)-1.0);sh=float(r.mean()/sd*(252.0**0.5)) if sd>0 else 0.0
    pk2=np.maximum.accumulate(nav);mdd=float((1.0-nav/pk2).max())
    rn=np.asarray(Ha["ret_net"],float) if len(Ha) else np.zeros(0)
    tw=float((rn>0).mean()) if len(rn) else 0.0
    print(f"DD10 nav={float(nav[-1]):.4f} ann={ann:.4f} sh={sh:.4f} mdd={mdd:.4f} tradewin={tw:.4f} n={len(rn)} cash={float(sum(cr)/len(cr)):.4f}",flush=True)
    np.savez_compressed(O,nav=nav,H=Ha,days=od)
if __name__=="__main__":
    main()
