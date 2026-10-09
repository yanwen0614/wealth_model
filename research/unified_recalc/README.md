# 统一口径重算+显著性 unified_recalc（2026-10-09）

> 深审纠偏产物：同脚本`eval_three_way`同定义、交集日期、只用npz自带true_ret。
> 2026烧掉只看图景；禁用重叠累乘。

## 脚本

- `scripts/s1_unified.py`：VAL common=232天、TEST common=149天重算IC/spread
- `scripts/s2_boot.py`：块bootstrap（块20天/B2000/seed42）配对差CI+P(>0)

## 结论

> 见 `research/README.md` 总表（结论只写注册表一份，此处不重复）。
> 一句话：树胜A显著、与B相当，spread/NAV是噪声。

## 产物

- `artifacts/{unified_ic,common_dates,boot_ic,boot_spread}.json`（已入库，csv留TEMP）
