# W1执行机会覆盖诊断：最终更正版

日期：2026-10-27。以本报告及同目录`semantic_erratum_20261027_zh.md`为最终口径；此前v1/v2文件保留，v2中“仅由训练not_trading解释5条缺bar”的文字由本报告更正。

## 固定排名与分母

信号478,369行、4,186码、118日。排名按当日`status=ready`且`exp_ret` finite的全宇宙；exp_ret降序、code升序，和主区`CnnOrderStrategy._rank_targets`一致。执行数据不参与排序。`buy_eligible`仅门控新BUY。E日rankable 4,033条、BUY资格0；排名保留，E日三条前日Top5的rank>10退出代理仍需报价。全窗排名机会879=Top5买入585+rank>10退出代理294；代理不是实际持仓。

## 三类结论

- **A 日线机械模型条件GO：4/879**。000151.SZ 2021-04-02/04-06与000301.SZ 2021-06-25/06-28。HDF各码122/122日覆盖；原始ST/SUSP均"0"，直接reference和绝对界可用，raw前收匹配reference，OHLC在绝对界内。允许将存档日字段作为预先声明的机械模型输入；时间戳不能证明盘前可见性，SQL无行继续unknown。
- **B 输入unknown或需广覆盖假设：875/879**。5条无bar的具体裁定见勘误：均有SQLite逐码逐日正向事件`是否停牌=1`（字段映射对应`IS_SUSP_SEC`），这是独立于训练文件的停牌证据；训练`not_trading`只是旁证。其余SQL无行不得当作verified normal。无bar日不撮合，有持仓则保留等待；不得假造bar或成交。
- **C 真实9:30成交：NO-GO**。日线数据不含队列、盘口、订单到达时间或逐笔成交；这不否定A层日线机械模型。

全局稀疏表前提仍须显式承担：供应商每码完整响应、缺码检测与重试、SDK及过滤版本固定、逐码生命周期和公司行动/特殊reference覆盖。4185/4186水位只表明可重查，不构成逐日完整证明。±4.5%仅在沪深普通股、reference>1、tick=0.01等前提下为条件数学包络，不是官方限价，不打开known标记。已查190个HDF中172码与信号交集；不推断未查缓存中其他代码无数据。

本次只读；未补采API、未跑收益/IC、未改业务代码、环境、主区或Git。最终复现入口为`verify_final_evidence.py`，其逐项输出为`final_verification.json`；历史`diagnose_coverage.py`会重生旧口径，不用于最终复现。此前`semantic_correction_zh.md`保留作历史v2，其缺bar解释与reference>0包络文字已被本报告/勘误取代。详细证据见勘误及`field_complete_semantic_cases_v2.csv`；旧v1/v2文件保留。
