# 精确优先第一批 precision（2026-10）

> 目标：把目标从IC翻译成`精确=P(true>0|选中)`，规则选择只看VAL2025，TEST2026仅图景。
> 大npz不入库，留`%TEMP%/opencode/precision/`与`logs/`。

## 脚本

- `scripts/precision_batch1.py`：`--task curves/pairs/veto`
  - curves：各模型precision-coverage曲线（K=1~500）
  - pairs：交集（A/B×HGB/XGB，N=10/50/200）与双horizon（H5∩H10）
  - veto：输家否决（底分位剔除，q=0.1/0.2）

## 结论

- VAL：B-25 K200 0.587→B×HGB交集0.629（容量12.6%）、A×HGB 0.638（8.2%）；
  否决+0.007~+0.018全正但小；H5∩H10不行；K=10可执行口径虚高4~5pp。
- 2026烧掉样本下全部坍塌0.42~0.50：精确规则不跨regime。
- 操作点：K=100~200，open-open计量；K=10只诊断。

## 产物

- `artifacts/precision_{curves,pairs,veto}.json`（已入库）
- 全量npz与`precision_smoke.json`留TEMP（诊断用，不入库）
