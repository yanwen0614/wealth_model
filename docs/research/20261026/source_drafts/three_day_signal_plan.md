# 半年无标签依赖信号生成：最小实施计划

## 需求与边界
- 目标：完整半年每个可形成 60 行因果窗口的代码/决策日输出 `exp_ret`，不因 H10 真值缺失而删信号；真值独立列可为 NaN。
- 特征、归一化、模型输出须与 checkpoint 训练契约一致；不改变 `data/dataset.py`、`train.py` 与训练路径。
- checkpoint 必须显式指定并通过训练 config 身份校验；首版限定 LABEL_MODE=excess、F53、relative、seq_len=60、H10、schema/bins，无 latest 自动选择；未来同配置 checkpoint 可复用。
- `is_trading`、warmup、上市历史不足、停牌/数据缺失须报告原因；全期决策日历与末期清算 buffer 分开，buffer 不发新买入信号。
- 当前阶段只在 CPU 小型合成 parquet 上验证；不启动真实全量推理，不占 GPU/大内存。

## 只读分析结论
- `data.reader.build_groups` 在生成窗口索引前要求 `future_ret[label_pos]` 有限，且 `n < seq_len+horizon+1` 会跳过股票；延长 parquet 仍不能消除此资格偏差。
- 特征原始列读取、`is_trading` 过滤、相对变换均可复用 `data.reader` 的读表/过滤函数和 `data.scaler.RelativeScaler`；相对变换无 fit/state。
- 评估模型构造、checkpoint 读取、中心点 `DEFAULT_CENTERS` 可参考 `scripts/eval_bins_mapping.py`；它将标签化 Dataset 与推理、指标紧耦合，不能直接用于 signal-only。
- 新增独立生成器可实现因果分组/窗口，不需要修改共享 `ParquetDataConfig`、`reader.py`、`dataset.py` 或 cache。
- 本首版显式拒绝 cs_rank/mkt_factors/per_code/rolling，不实现第二套归一化；仅复用 `RelativeScaler` 与 schema。
- 当前 `eval_bins_mapping.py` 的 checkpoint 解析允许 latest 回退；新 CLI 要求用户显式给单一 checkpoint 路径、决策日期和真实交易日历，不做目录推断。

## 变更文件与占用
- 新增 `scripts/generate_walkforward_signals.py`：独立 CLI / 核验身份 / 因果特征窗口 / 批量模型推理 / 输出元数据；原始信号表与 adapter 数组均保留 E 日有效预测，`buy_eligible` 作为元数据；执行端必须按 execution_date 裁决 E 后拒 BUY、允许 buffer SELL。
- 新增 `tests/unit/scripts/test_walkforward_signals.py`：临时小型 parquet、CPU 覆盖标签末期、晚于 origin 的 59 行 context、长停牌、上市历史不足、buffer资格和与旧 Dataset 首日/次日完整张量逐位一致。
- 夹具复用 `tests/unit/data` 现有 parquet 构造惯例；不创建持久大数据夹具，不改任何共享生产文件。
- 父工程会话 `ses_e8c5355c1ffe90QM9CMG7qL6e4` 与生成器 `ses_e8c35e7caffeB1yMULTp4Irnqm` 的费用/清算/身份文件不读取写入或修改。

## 执行顺序
1. 核对用户显式传入 checkpoint 的 config/训练身份字段；缺失/矛盾则拒绝运行并报告，不猜测补值。
2. 实现只新增文件的 signal-only 预处理、模型推理和结果元数据；输入全期决策日历，清算 buffer 日期显式标识并抑制新买入信号。
3. 先写并运行 CPU 合成测试；不执行 smoke、全套训练或真实 parquet 推理。
4. 独立审查新文件和测试，修复阻断项；说明是否存在需主会话授权的共享接口缺口。
5. 交付测试结果、变更路径、身份/日历语义及全量运行所需资源安排；全量运行留待主会话排程。

## 验收条件 / 风险
- 对重叠有标签样本，新信号的特征张量与评估路径逐样本数值一致，`exp_ret` 在容差内一致。
- 每股只留决策期前最后 59 条有效交易 context（逐 row group 扫描，不按自然日截断）及期内行；未来数据不得改变 `exp_ret`。
- H10 真值仅作可选审计字段，不参与行资格；无真值时保留 exp_ret，禁止以 0 代替真值计算指标。
- 风险：row group 流式仍扫描源文件各 row group；CPU I/O、全半年保留数组及全量峰值未经真实数据预检，需主会话先做小范围资源预检。批读取上限 131072 行；峰值字段为数值载荷估算，不是实测 RSS。
- 风险：清算 buffer 从显式基准日历取得；代码只标记首尾决策日买入资格，最终真实成交约束由父工程执行器负责。
- 风险：旧 Dataset 的首 context P 特征因缺少前一行 close 回退为 0；小样本确认新首版严格复现该契约。
