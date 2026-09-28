# paper_jkx 冻结声明（2026-09-27 冻结，2026-09-28 源码入库）

* 2026-09-28 起**源码入库**（`src/` + `README.md` + 本文件），与主链路零耦合；
  `logs/` 产物（权重/矩阵/报告）仍忽略不入库。
* 此前全程 untracked 的纪律已由用户显式解除，此后 `paper_jkx/src` 改动走正常提交。
* 研究已收口：多头 target 框架内 2026 无解，唯一正收益 I5-t20（+15.2%）。
* 七路验证全灭或边际，结论见 `README.md` + `docs/archive/paper_jkx_2024-2026_seven_routes.md`。
* 产物：`logs/cnn_I{5,20,60}R*.pth`（权重）、`logs/preds_*_{2024,2025,2026}.npz`（预测）、
  `logs/ohlc_full_*.npz`（矩阵）、`logs/backtest_*/gate_*/hedge_*/regime_*/`（报告）。
  全部可重跑（`src/train.py → eval_predict.py → report_nav.py`），本次整理不动。
* 后续只允许读，不再新增验证方向。如需动框架（做空/改选择机制），另立项。
