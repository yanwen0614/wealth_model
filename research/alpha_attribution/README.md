# α/m归因横评 alpha_attribution（2026-10）

> 口径：`r=m_t+α`逐日截面分解，与`rv_R346.py`逐位一致（J30-25复核通过）。
> 树2026 `true_ret` 25980个NaN按仅有效标签过滤（`tree_fixed`为最终口径）。

## 脚本

- `scripts/alpha_m.py --models ... --tag ...`：统一分解+topN归因
- `scripts/alpha_m_summary.py`：跨模型汇总表

## 结论

> 见 `research/README.md` 总表（结论只写注册表一份，此处不重复）。
> 一句话：2025靠m，2026唯树头部α守住，辅助/集成理据增强。

## 产物

- `artifacts/alpha_m_{main,jkx,tree_fixed}.json`（已入库）
- 复跑：`uv run --project . python research/alpha_attribution/scripts/alpha_m.py --models all --tag all`
