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

# 形状注册:灰度沿用 3*n_days 宽(原论文口径); I30-color 为 4px/天彩色 [96,120,3]
SHAPES = {5: (64, 15, 1), 20: (128, 60, 1), 30: (96, 120, 3), 60: (192, 180, 1)}


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


# --- I30-color 冻结规格(2026-09-29): 后复权 OHLC, 4px/天, 红涨绿跌实体,
#     半透明均线(蜡烛置顶不被遮挡), 灰量柱 + 橙/青振荡器. ---
RGB_PPD = 4
RGB_PRICE_H, RGB_VOL_H, RGB_OSC_H = 60, 18, 18
RGB_MA_ALPHA = 0.45
UP = np.array([230, 45, 45], np.uint8)      # 涨=红
DN = np.array([60, 210, 70], np.uint8)      # 跌=绿
MA_COLORS = (np.array([255, 255, 255]) * RGB_MA_ALPHA,
             np.array([255, 220, 0]) * RGB_MA_ALPHA,
             np.array([220, 80, 255]) * RGB_MA_ALPHA)
VOL_COLOR = np.array([110, 110, 110], np.uint8)
OSC_BAR_COLOR = np.array([230, 150, 40], np.uint8)
OSC_LINE_COLOR = np.array([0, 230, 230], np.uint8)


def _rgb_prow(p, pmax, pmin, top, h):
    return top + round((pmax - p) / (pmax - pmin) * (h - 1))


def _rgb_line(img, xs, ys, color):
    for k in range(len(xs) - 1):
        x1, x2, y1, y2 = xs[k], xs[k + 1], ys[k], ys[k + 1]
        steps = max(1, x2 - x1)
        for s in range(steps + 1):
            x, y = x1 + s, round(y1 + (y2 - y1) * s / steps)
            if 0 <= y < img.shape[0] and 0 <= x < img.shape[1]:
                img[y, x] = color


def render_i30_rgb(o, h, l, c, v, ma5, ma20, ma60, osc_bar, osc_line):
    """I30-color 渲染: 后复权 OHLC -> uint8 [96,120,3].

    价格纵轴 max/min 含全部三条均线(体现相对长期均线位置); 均线先画(半透明),
    蜡烛后画(置顶); 量柱/振荡器各自窗内归一. 返回 uint8 RGB.
    """
    H = RGB_PRICE_H + RGB_VOL_H + RGB_OSC_H
    W = RGB_PPD * len(o)
    img = np.zeros((H, W, 3), dtype=np.uint8)
    o, h, l, c, v = (np.asarray(x, float) for x in (o, h, l, c, v))
    mas = [np.asarray(m, float) for m in (ma5, ma20, ma60)]
    ps = [h[np.isfinite(h)], l[np.isfinite(l)]]
    ps += [m[np.isfinite(m)] for m in mas if np.any(np.isfinite(m))]
    ps = [s for s in ps if s.size]
    if ps:
        allp = np.concatenate(ps)
        pmax, pmin = float(allp.max()), float(allp.min())
        if pmax > pmin:
            for i in range(len(o)):
                x0 = i * RGB_PPD
                if not (np.isfinite(h[i]) and np.isfinite(l[i])):
                    continue
                r1 = _rgb_prow(h[i], pmax, pmin, 0, RGB_PRICE_H)
                r2 = _rgb_prow(l[i], pmax, pmin, 0, RGB_PRICE_H)
                color = UP if c[i] >= o[i] else DN
                img[min(r1, r2):max(r1, r2) + 1, x0 + 1] = color       # 影线
                ro = _rgb_prow(o[i], pmax, pmin, 0, RGB_PRICE_H)
                rc = _rgb_prow(c[i], pmax, pmin, 0, RGB_PRICE_H)
                img[min(ro, rc):max(ro, rc) + 1, x0 + 1:x0 + 3] = color  # 实体
            for m, col in zip(mas, MA_COLORS):
                xs = [i * RGB_PPD + 1 for i in range(len(o)) if np.isfinite(m[i])]
                ys = [_rgb_prow(m[i], pmax, pmin, 0, RGB_PRICE_H)
                      for i in range(len(o)) if np.isfinite(m[i])]
                if len(xs) > 1:
                    _rgb_line(img, xs, ys, col.astype(np.uint8))
    vtop = RGB_PRICE_H
    if np.any(np.isfinite(v)):
        vmax = float(np.nanmax(v))
        if np.isfinite(vmax) and vmax > 0:
            for i in range(len(v)):
                if np.isfinite(v[i]) and v[i] > 0:
                    bh = max(1, round(v[i] / vmax * RGB_VOL_H))
                    img[vtop + RGB_VOL_H - bh:vtop + RGB_VOL_H,
                        i * RGB_PPD:(i + 1) * RGB_PPD] = VOL_COLOR
    otop = RGB_PRICE_H + RGB_VOL_H
    if osc_bar is not None:
        b = np.asarray(osc_bar, float)
        if np.any(np.isfinite(b)):
            bmax = float(np.nanmax(np.abs(b)))
            if np.isfinite(bmax) and bmax > 0:
                for i in range(len(b)):
                    if np.isfinite(b[i]):
                        bh = max(1, round(abs(b[i]) / bmax * RGB_OSC_H))
                        img[otop + RGB_OSC_H - bh:otop + RGB_OSC_H,
                            i * RGB_PPD:(i + 1) * RGB_PPD] = OSC_BAR_COLOR
    if osc_line is not None:
        q = np.asarray(osc_line, float)
        fin = q[np.isfinite(q)]
        if fin.size and np.ptp(fin) > 0:
            qmax, qmin = float(fin.max()), float(fin.min())
            xs = [i * RGB_PPD + 1 for i in range(len(q)) if np.isfinite(q[i])]
            ys = [_rgb_prow(q[i], qmax, qmin, otop, RGB_OSC_H)
                  for i in range(len(q)) if np.isfinite(q[i])]
            if len(xs) > 1:
                _rgb_line(img, xs, ys, OSC_LINE_COLOR)
    return img
