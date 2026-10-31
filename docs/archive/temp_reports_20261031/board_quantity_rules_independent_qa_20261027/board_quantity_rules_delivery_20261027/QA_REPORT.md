# 独立质量门报告

**结论：PASS（冻结版）**。审查期间4个源文件hash前后均与指定冻结值一致；未发现P0/P1/P2源码缺陷。7关通过，backtest测试、RED/GREEN探针、Ruff与指定解释器Pyright均通过。

## 冻结身份

| 文件 | SHA256（审查前后相同） |
|---|---|
| `backtest/cnn_adapter/quantity_rules.py` | `d88ed93ab5e41b698f1765bce37571f60707989d7ea2c4a7377340960f3dba8c` |
| `backtest/cnn_adapter/staged_order_strategy.py` | `4101d8af474727ebd55ab83ccb38e21dbf8aef1d5401f279336987967f08be42` |
| `tests/unit/backtest/test_quantity_rules.py` | `414855dd66312570e368f9eefeffcb22f6f28bcc2dfa4727ee9996ed2dc5da3d` |
| `tests/unit/backtest/test_staged_order_strategy.py` | `d391b88c79ce43a5ae305265b012c72365ac51323dfda1074205f52e51bf727f` |

## 七关结论

1. **范围 PASS**：日期、数量和方向校验集中于数量规则；无符合项时 resolver 拒绝猜测；超过单笔上限拒绝，不拆单。
2. **复用 PASS**：策略 BUY/SELL 共用 `QuantityRule.validate`；数量规则失败发生于 `schedule_tranche` 之前，不生成订单意图。
3. **契约 PASS**：科创板限价 min=200/step=1/max=100000；未错误套用200倍数。主板规则参数可表达历史 min=100/step=100/max=1000000。
4. **财务状态 PASS**：RED有单；GREEN 100股拒绝后无OrderIntent、无order_id、requested_shares=0，tranche为REJECTED，commitment仍是账面承诺而非订单/成交污染。200与300股可排单。
5. **错误拒绝 PASS**：未知日期/代码、规则歧义、无效来源/方向/日期/股数均拒绝；全额卖出例外仍先受maximum约束。
6. **可验证性 PASS**：RED独立探针明确输出100股BUY；GREEN数量规则6项、策略12项及完整 backtest 307项运行通过。
7. **兼容 PASS**：`quantity_rule_resolver=None` 保持旧行为，RED探针证明确实会发出100股订单。

## 执行证据

- RED_unwired_gate：exit 0；未挂 resolver 时发出100股买单；挂规则后100拒绝、200/300通过。
- GREEN_rules：6 tests，OK；GREEN_strategy：12 tests，OK。
- 完整命令 `python -B -m unittest discover -s tests/unit/backtest -t . -v`：307 tests，OK，2 skipped，exit 0。两项skip因本机真实parquet样本缺失而显式跳过。
- Ruff 0.16.5：4个冻结文件 `check --no-cache`，All checks passed，exit 0。
- Pyright 1.1.411：指定虚拟环境解释器与 `--pythonpath`，4文件0 errors/0 warnings，exit 0。先前未指定pythonpath的10条外部导入错误已由正确命令消除，不列为基线缺陷。
- 额外非法输入探针5/5拒绝，exit 0；见 `RED_unwired_gate/invariant_probe.py`。

## 缺陷与交付边界

- **P0：无；P1：无；P2：无。**
- 生产应用必须在调用策略时接入覆盖相应历史日期和证券类别的可信 resolver；兼容设计允许 `None`，因此单独构造策略时数量规则不会自动执行。该项是运行配置前置条件，不是冻结实现偏离既定兼容契约。
- 规则表、证券历史板别映射及生产回测收益验收不在本次冻结4文件质量门内；本PASS不代表已完成生产规则数据部署或策略收益验收。
- 历史证据：项目研究文档列明SSE 2019官方通知及PDF哈希；主板参照用户指定的SSE 2020原文与暂缓条款。没有使用2026现行规则替代历史版本。

详细命令与结果见 `RED_unwired_gate/run.log`、`GREEN_rules/run.log`、`GREEN_strategy/run.log`、`tests_backtest.log`、`ruff.log`、`pyright.log`；逐关清单见 `REVIEW_CHECKLIST.md`。
