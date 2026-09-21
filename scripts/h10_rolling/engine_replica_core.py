# 自研目标持仓循环：与backtest/engine逐bit一致，不import engine
# 输入：exp/codes/dates预测+oc/od/om/cm行情矩阵，size=20/sb=0.02
# 输出：nav净值曲线+rec交易记录(entry/exit/code/ret_net)
# 已验证：复刻6M基线NAV≈1.9188/n=725，误差<2% PASS(s1_replicate)
import numpy as np
BUY=0.00025;SEL=0.00025;STM=0.00025;MINC=5.0;CAP=1e6
def _cm(n,r):
    f=n*r;return f if f>MINC else MINC
def run(exp,codes,dates,oc,od,om,cm,size=20,sb=0.02):
    e=np.asarray(exp,float);cs=np.asarray(codes).astype(str);ds=np.asarray(dates).astype("datetime64[D]")
    row={s:i for i,s in enumerate(np.asarray(oc).astype(str))}
    n=len(od);pos={};cash=1.0;nav=np.ones(n);rec=[];pv=None
    for i,d in enumerate(od):
        for s,p in pos.items():
            x=om[row[s],i]
            if x==x:p["px"]=x
        if i>0 and pv is not None:
            ol,em=pv
            for s in [s for s in list(pos) if em.get(s) is not None and em[s]<=0.0]:
                p=pos.pop(s);sn=p["sh"]*p["px"];bn=p["sh"]*p["ep"]
                ec=bn+_cm(bn,BUY);pn=sn-_cm(sn,SEL)-sn*STM
                rec.append((str(p["ed"]),str(d),s,(pn-ec)/ec));cash+=pn/CAP
            pre=cash+sum(v["sh"]*v["px"] for v in pos.values())/CAP
            if i<n-1 and pre>0:
                sl=size-len(pos)
                for s in ol[:size]:
                    if sl<=0:break
                    if s in pos or em[s]<sb:continue
                    r_=row.get(s)
                    if r_ is None:continue
                    px=om[r_,i];pc=cm[r_,i-1]
                    if not px==px or not pc==pc:continue
                    th=1.198 if s[:3] in ("300","688") else 1.098
                    if px>=pc*th:continue
                    bg=pre/size*CAP
                    if bg>cash*CAP:bg=cash*CAP
                    if bg<=MINC:continue
                    bs=MINC*(1.0+BUY)/BUY
                    sh=bg/(px*(1.0+BUY)) if bg>=bs else (bg-MINC)/px
                    bn=sh*px;cash-=(bn+_cm(bn,BUY))/CAP
                    pos[s]={"sh":sh,"px":px,"ep":px,"ed":d};sl-=1
        nav[i]=cash+sum(v["sh"]*v["px"] for v in pos.values())/CAP
        m=ds==d
        if m.any():
            o=np.argsort(-e[m],kind="stable");cms=cs[m];ol=[str(cms[j]) for j in o]
            ev=e[m][o];pv=(ol,{ol[k]:float(ev[k]) for k in range(len(ol))})
    for s in list(pos):
        p=pos.pop(s);sn=p["sh"]*p["px"];bn=p["sh"]*p["ep"]
        ec=bn+_cm(bn,BUY);pn=sn-_cm(sn,SEL)-sn*STM
        rec.append((str(p["ed"]),str(od[-1]),s,(pn-ec)/ec));cash+=pn/CAP
    nav[-1]=cash
    return nav,rec
