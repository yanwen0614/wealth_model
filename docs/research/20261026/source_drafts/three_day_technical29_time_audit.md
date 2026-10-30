# 29个纯技术 raw 特征时点审计（阶段报告）

核查范围：仅 P18 + R11；只读源码。训练 footer 提交 `26c3db036a266f5765d8cdee4ef352c56d6ee1e9`。没有读取/扫描4GB训练文件，没有调用API、训练或计算策略收益。

## 已定位的实现

- `src/core/factor/factors/technical/trend.py`：MA5/10/20/60 `compute` 分别在32/54/76/98行调用 rolling mean，窗口即5/10/20/60；EMA12/26 在120/142行调用 span 12/26；DMI/ADX 188/230行调用 `OperatorEngine` period=14。fallback 在193-206、232-246行使用 `diff`、前值 `close.shift()` 与 `ewm(alpha=1/14, adjust=False)`，未见负 shift 或居中窗口。
- 同文件 SAR 263-315行：生产优先 `OperatorEngine(prefer_talib=True)`；仅无后端时走本地递推，初始取首最多5行极值（277-286），逐行递推至当前行（288-313）。本地 fallback 没有未来索引。
- `src/core/factor/factors/technical/volatility.py`：BOLL 29-40行用20日 rolling mean/std（ddof=0）；ATR 56-72行 period=14，fallback 用 `close.shift()` 和 Wilder `ewm(adjust=False)`；KELCH 87-107行 EMA span20、ATR period20；STD5/10/20 在122-130、145-153、168-176行用同长度 rolling std、ddof=0。
- `src/core/factor/factors/technical/trend_duokong.py`：trend_duokong 26-36行及 dev 73-85行用 close 的12/20/120/250 rolling mean；shortline 51-58行双重 span10 EMA。
- 已确认上述因子声明的依赖仅 `close` 或 `close/high/low`（相应类 dependencies 行）；这些实现没有声明指数、财务输入。

## 当前可行动判定与边界

1. 已读到的 Python 公式是单代码逐时点 trailing/递推形式：所见调用没有 `center=True`、`shift(-N)`、`bfill` 或跨样本 `fit`。但底层 `OperatorEngine.rolling` / TA-Lib 实现尚未逐项对照，不能把这句话升级为整个生成链的证明。
2. 窗口起始不足值：纯 pandas/TA-Lib rolling 的生产预热行为、OperatorEngine 缺失值/回退分派，需继续核对 `operators`；明确可见的部分仅为 fallback ewm 从首个可计算值递推，`close.shift()` 首行自然缺前值。故各列首段 NaN/填充确切规则目前标 **unknown**，尚未发现源码显式 bfill。
3. 价格口径影响：已读 `three_day_price_lineage.md` 第32-34、56-61行：footer 指向上述训练提交，但扩展因子完整生成入口未定位、无生成日志/源文件 hash 证明整份 F60 由同一不可变构建产生；其第38、59行确认训练 OHLC 为日线源价乘后复权因子，F60 未存因子。故 close 派生技术指标（包括 MA/EMA/STD、trend 三列）会继承该后复权历史序列；因子若按历史有效日向前应用，尚需确认是否存在跨日因子回写或供应商事后修订。不能据当前源码声称训练产物已逐值重验。

## 尚未定位（明确 unknown）

## 补查：alpha rolling 与底层算子

- `src/core/factor/factors/alpha/volatility.py`：volatility_5d/10d/20d 分别在26-36、51-60、75-84行先 `close.pct_change()`，再 rolling std 窗口5/10/20、ddof=1。无显式 shift(-N)/bfill/全样本拟合；当前期收益率进入当前期窗口，值在收盘 close 可得后才可用。
- `src/core/factor/factors/alpha/liquidity.py`：amihud 26-34行以 `abs(pct_change)/(close*volume+1)` 做 trailing `.rolling(20).mean()`；volume_ratio 49-58、73-82行明确先 `volume.shift(1).rolling(5/10).mean()`，以当日量除此前5/10日均量。未见前视操作。
- `src/core/factor/operators/engine.py`：66-105行先 TA-Lib（若因子设置 prefer_talib），均值/标准差等不支持时走 pandas；101-105路由聚合。fallback 161-170行显式 `min_periods=window`，不足窗口输出 NaN，ddof 默认1。无中心化参数。
- 同文件 EMA fallback 187-193行以 SMA 满窗作为预热门槛，再取递推 EWM；ATR fallback 204-218行亦以 period SMA 预热后使用 Wilder EWM；两者 `adjust=False`，`close.shift()` 为正向一阶前值。TA-Lib 路径见 `talib_adapter.py` 90-148、155-215行：直接把完整序列传给 EMA/ATR/ADX/PLUS_DI/MINUS_DI/SAR，并按原 index 返回；该适配层没有回填/负移位。TA-Lib 自身 lookback 行为在此表现为 NaN。
- `trend.py` 的 MA 因子强制 `prefer_talib=False`（28/50/72/94），故使用 pandas fallback、前 window-1 行 NaN；STD/BOLL 同理（volatility.py 30、123、146、169）。EMA/DMI/ADX/SAR prefer_talib=True，生产后端优先 TA-Lib；若不可用，则按 engine fallback 或各因子显式 fallback。跨环境后端选择可能改变 warmup/数值细节，生成时实际后端未见身份记录。

## 因果性结论（源码定义层）

目前 29 列均已找到因子定义：P18 在 trend.py、volatility.py、trend_duokong.py；R11 在 alpha/volatility.py 与 alpha/liquidity.py。定义层输入仅为当前及历史 OHLCV，不依赖指数或财务列；所见 rolling 为 trailing，递推 EWM 只依赖当前/过去值，没有 `center=True`、`shift(-N)`、`bfill` 或整样本统计。因此可以作为**源码公式层的因果候选集合**。但未执行小型 prefix/append 验证，也未逐项审查 trend_duokong 上游 operator 与所有导出改写步骤；结论范围仅源码静态检查。

## 快照身份仍中断

`three_day_price_lineage.md` 第32-34行记录 footer git_hash 与 export_time，且当前已知基础量价导出源码和该提交一致；但扩展因子的生成入口/当时因子代码 hash、运行后端（TA-Lib 有无）、每股输入序列和导出阶段填充处理没有不可变快照证据。因此【函数定义因果】初步支持；【生成快照可追溯】不完整；【F60实际产物逐值重验】未做。后复权因子可能影响当前及后续技术指标的输入价格尺度/历史可见版本，不能由因子公式因果推出供应商当时版本无修订或生成全程无前视。

## 尚待补充

逐项核对 29 列导出/拼接是否重排、补值、截断；未运行人工 OHLCV 前缀验证（该验证仅可测函数定义因果，不会补成训练产物逐值证明）。当前建议：29列在源码层可作为较少数据依赖的保守候选；用于新训练前应显式仅选这29列，并先固定生成代码与 TA-Lib/backend 版本、审计输入后复算，不宣称现有 F60 已通过 PIT。

## 生成入口追踪（部分）

- `scripts/compute_all_factors.py` 当前源码约 220 行调用 `FactorEngine.compute_and_save(..., use_adjusted=True)`；`src/core/factor/engine.py` 57-89行确认默认/显式 adjusted 时从 `_load_adjusted_data` 读取，逐因子调用 `factor.compute(data)`（91-118行）。因此当前定义链确实以复权K线为技术因子输入。
- `engine.py` 229-238行定义 `_warmup_for_factors`，趋势前缀回看档为 250；增量路径 263-284行读 warmup 窗后重算并切出写入窗口。全量写盘路径的 warmup/日期边界与目标 F60 扩展文件的实际生成命令仍未由 footer 证明。
- 对训练提交执行 `git show 26c3db0:src/core/factor/factors/technical/trend.py`，MA/EMA/DMI/ADX/SAR 对应公式与当前读取内容一致；`git show 26c3db0:scripts/compute_all_factors.py` 显示同样以 FactorEngine 及 `use_adjusted=True` 批量生成。该比对只覆盖这两个文件，不代表全部29因子模块和扩展导出程序已逐文件锁定。

注意：`volume_ratio_5d/10d` 的当日分子使用当日 volume，因此只能在当日成交量完整后形成收盘特征；Amihud 与波动率同样含当日收盘收益/成交量。若策略在开盘执行，必须滞后一交易日使用这些列。29列源码层因果不等于开盘可见。
