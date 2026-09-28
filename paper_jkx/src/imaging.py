"""论文 Sec.I 成图 + v2 扩展:高分辨率、多均线叠加、振荡器条.

版式 v1(论文原样):每一天 3 像素宽(左 open/中 high-low/右 close),
价格区上 4/5,量柱下 1/5,纵轴窗内 max/min 拉满,黑底白字.
v2:高度翻倍 {5:64, 20:128, 60:192};价格区叠加 ma_20/ma_60 长均线
(与窗内均线同缩放到价格区,体现价格相对长期均线位置);
底部在量柱下再加 1/5 振荡器条(volume_ratio_5d 柱 + macd 连线,
各用自窗缩放到条内).缺失值留空,与论文缺失处理一致.
"""
import numpy as np

HEIGHTS = {5: 64, 20: 128, 60: 192}


def _prow(p, pmax, pmin, top, h):
    r = (pmax - p) / (pmax - pmin)
    return top + round(r * (h - 1))


def _draw_line(img, xs, ys):
    for k in range(len(xs) - 1):
        x1, x2, y1, y2 = xs[k], xs[k + 1], ys[k], ys[k + 1]
        steps = max(1, x2 - x1)
        for s in range(steps + 1):
            x = x1 + s
            y = round(y1 + (y2 - y1) * s / steps)
            if 0 <= y < img.shape[0]:
                img[y, x] = 1.0


def render_ohlc_image(o, h, l, c, v, ma, n_days=5):
    """v1 兼容入口:OHLC + 窗内均线 + 量柱(新分辨率)."""
    return render_plus(o, h, l, c, v, [ma], None, None, n_days,
                       price_frac=0.8, osc_frac=0.0)


def render_plus(o, h, l, c, v, ma_list, osc_bar, osc_line, n_days=5,
                price_frac=0.6, osc_frac=0.2):
    """v2 成图,返回 float32 [H,W] ∈ {0,1}.

    o/h/l/c/v:长度 n 一维数组;ma_list:叠加到价格区的均线数组列表;
    osc_bar/osc_line:画到振荡器条的柱/线(可为 None 关闭).
    """
    H = HEIGHTS[n_days]
    W = 3 * n_days
    img = np.zeros((H, W), dtype=np.float32)
    price_h = int(H * price_frac)
    osc_h = int(H * osc_frac)
    vol_h = H - price_h - osc_h
    o = np.asarray(o, float)
    h = np.asarray(h, float)
    l = np.asarray(l, float)
    c = np.asarray(c, float)
    mas = [np.asarray(m, float) for m in (ma_list or [])]
    # 价格区缩放:OHLC + 全部叠加均线共同 max/min
    ps = [h[np.isfinite(h)], l[np.isfinite(l)]]
    ps += [m[np.isfinite(m)] for m in mas if np.any(np.isfinite(m))]
    allp = np.concatenate([s for s in ps if s.size]) if any(s.size for s in ps) else None
    if allp is not None and allp.size and np.ptp(allp) > 0:
        pmax, pmin = float(allp.max()), float(allp.min())
        for i in range(n_days):
            x0 = i * 3
            if np.isfinite(h[i]) and np.isfinite(l[i]):
                r1, r2 = _prow(h[i], pmax, pmin, 0, price_h), _prow(l[i], pmax, pmin, 0, price_h)
                if r1 > r2:
                    r1, r2 = r2, r1
                img[r1:r2 + 1, x0 + 1] = 1.0
            if np.isfinite(o[i]):
                img[_prow(o[i], pmax, pmin, 0, price_h), x0] = 1.0
            if np.isfinite(c[i]):
                img[_prow(c[i], pmax, pmin, 0, price_h), x0 + 2] = 1.0
        for m in mas:  # 叠加均线:中列连线
            xs = [i * 3 + 1 for i in range(n_days) if np.isfinite(m[i])]
            ys = [_prow(m[i], pmax, pmin, 0, price_h) for i in range(n_days)
                  if np.isfinite(m[i])]
            if len(xs) > 1:
                _draw_line(img, xs, ys)
            elif xs:
                img[ys[0], xs[0]] = 1.0
    # 量柱区:窗内 max 归一,底部向上
    vv = np.asarray(v, float)
    vtop = price_h
    if np.any(np.isfinite(vv)):
        vmax = float(np.nanmax(vv))
        if np.isfinite(vmax) and vmax > 0 and vol_h > 0:
            for i in range(n_days):
                if not np.isfinite(vv[i]) or vv[i] <= 0:
                    continue
                bh = max(1, round(vv[i] / vmax * vol_h))
                for k in range(3):
                    img[vtop + vol_h - bh:vtop + vol_h, i * 3 + k] = 1.0
    # 振荡器条:柱用自窗 max 归一,线用自窗 min/max 归一
    otop = price_h + vol_h
    if osc_h > 0:
        if osc_bar is not None:
            b = np.asarray(osc_bar, float)
            if np.any(np.isfinite(b)):
                bmax = float(np.nanmax(np.abs(b)))
                if np.isfinite(bmax) and bmax > 0:
                    for i in range(n_days):
                        if not np.isfinite(b[i]):
                            continue
                        bh = max(1, round(abs(b[i]) / bmax * osc_h))
                        for k in range(3):
                            img[otop + osc_h - bh:otop + osc_h, i * 3 + k] = 1.0
        if osc_line is not None:
            q = np.asarray(osc_line, float)
            fin = q[np.isfinite(q)]
            if fin.size and np.ptp(fin) > 0:
                qmax, qmin = float(fin.max()), float(fin.min())
                xs = [i * 3 + 1 for i in range(n_days) if np.isfinite(q[i])]
                ys = [_prow(q[i], qmax, qmin, otop, osc_h) for i in range(n_days)
                      if np.isfinite(q[i])]
                if len(xs) > 1:
                    _draw_line(img, xs, ys)
                elif xs:
                    img[ys[0], xs[0]] = 1.0
    return img
