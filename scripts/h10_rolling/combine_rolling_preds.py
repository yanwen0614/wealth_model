# H10滚动预测拼接：合并A/B两段preds，去重后按日期排序
# 输入：两段preds npz(exp_ret/true_ret/dates/codes)，argv可覆盖默认Temp路径
# 输出：combined.npz(exp_ret/true_ret/dates/codes，去重排序后)
# 已验证：A/B无日期重叠，total约3年滚动窗口，s2回测直接消费此口径
import sys
import json
import numpy as np


A = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_A\preds_h10_roll_A.npz"
B = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_B\preds_h10_roll_B.npz"
O = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\yanwen\AppData\Local\Temp\opencode\h10_roll_bt\combined.npz"


def get(z):
    return (np.asarray(z["exp_ret"], float), np.asarray(z["true_ret"], float),
            z["dates"].astype("datetime64[D]"), np.asarray(z["codes"]).astype(str))


def main():
    a = np.load(A, allow_pickle=True)
    b = np.load(B, allow_pickle=True)
    ea, ta, da, ca = get(a)
    eb, tb, db, cb = get(b)
    e = np.concatenate([ea, eb]); t = np.concatenate([ta, tb])
    d = np.concatenate([da, db]); c = np.concatenate([ca, cb])
    keys = np.array([f"{x}|{y}" for x, y in zip(d.astype(str), c)])
    _, idx = np.unique(keys, return_index="first")
    e, t, d, c = e[idx], t[idx], d[idx], c[idx]
    o = np.argsort(d, kind="stable"); e, t, d, c = e[o], t[o], d[o], c[o]
    np.savez_compressed(O, exp_ret=e, true_ret=t, dates=d, codes=c)
    print("total:", len(e), "range:", d.min(), d.max(), flush=True)
    print("overlap_A_B:", len(set(da.astype(str)) & set(db.astype(str))), flush=True)
    for tag, fp in (("A", A), ("B", B)):
        try:
            import os
            fj = os.path.join(os.path.dirname(fp), "folds.json")
            fa = json.load(open(fj, encoding="utf-8"))
            print(tag, [(f.get("test_start"), f.get("test_end")) for f in fa], flush=True)
        except Exception as ex:
            print(tag, "folds.json跳过:", ex, flush=True)


if __name__ == "__main__":
    main()
