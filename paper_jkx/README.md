# paper_jkx — Jiang-Kelly-Xiu (2023) "(Re-)Imag(in)ing Price Trends" A 股复现
新开独立目录,不碰主链路 per-code/CNN-Transformer.

## 做法对照论文
- Sec.I 成图:`src/imaging.py`(3px/天,左open/中high-low/右close,均线连线,下1/5量柱,纵轴拉满)
- 成图 v2(`render_plus`):分辨率翻倍(5:64/20:128/60:192 px高,宽3*n_days),
  价格区叠加 ma_n/ma_20/ma_60,振荡器条为 volume_ratio_5d 柱 + macd 线
- Sec.II CNN:`src/models.py`(Conv5x3+BN+LeakyReLU+MaxPool2x1,2/3/4 block,dropout0.5,softmax二分类)
- Sec.III 标签:`y=1{未来R日收盘收益>0}`,70/30随机切分,Adam lr1e-5 batch128,早停2轮
- 组合:论文为十分位 H-L，本复现**复用现有回测链路**做多头 topN
  (`backtest.engine.run_backtest_target` + `scripts/build_ohlc_path.py` 全期矩阵
  + `scripts/run_backtest.py --mode target` 报告，含沪深300基准与 A 股费用模型)，
  不自写会计；`src/backtest.py` 仅做“概率→preds npz”格式转换。
- 标签与引擎对齐:open-open `open[t+1+h]/open[t+1]-1`(`data/labels.py` 口径);
  `exp_ret=prob-0.5`(保序,阈值类参数须关)。

## 运行
```bash
uv run --project . python -m paper_jkx.src.train --parquet data/test/train_data/*.parquet --n_days 5 --horizon 5 --max_codes 200 --epochs 3
uv run --project . python -m paper_jkx.src.eval_predict --parquet ... --ckpt paper_jkx/logs/cnn_I5R5.pth --max_codes 200
# 全量评估用 --max_codes 0; I60 大图推理需 --bs 128 (8GB 显存,默认 2048 会 OOM)
uv run --project . python -m paper_jkx.src.report_nav --preds <npz> --full_ohlc <矩阵> --sizes 20 100 --out_dir paper_jkx/logs/backtest_<组>_<年>
```
A 股划分:2013~2023 训练,2024 与 2025 分别作验证(周频 stride=n_days 全量)。

## 验证结果(2024/2025,现有引擎 target,绝对收益,无沪深300基准)
| 组 | 年 | target20 annual/sharpe/nav | target100 annual/sharpe/nav |
|---|---|---|---|
| I5/R5 | 2024 | +27.0%/0.78/1.256 | +21.8%/0.67/1.207 |
| I5/R5 | 2025 | +44.7%/1.86/1.426 | +58.6%/2.34/1.557 |
| I20/R20 | 2024 | -0.0%/0.21/1.000 | +2.2%/0.25/1.021 |
| I20/R20 | 2025 | +49.6%/2.06/1.472 | +48.3%/2.21/1.460 |
| I60/R60 | 2024 | +27.3%/0.89/1.260 | +24.6%/0.83/1.234 |
| I60/R60 | 2025 | +34.8%/1.78/1.332 | +33.8%/1.92/1.323 |
| I5/R5 | 2026.01~08 | +15.2%/0.70/1.094 | -1.2%/0.06/0.993 |
| I20/R20 | 2026.01~08 | -17.6%/-0.89/0.885 | -23.3%/-1.39/0.846 |
| I60/R60 | 2026.01~08 | -15.1%/-0.87/0.902 | -5.6%/-0.28/0.964 |

- 训练(2013~2023,早停2轮):I5 val 0.6894(ep4)/I20 0.6860(ep5)/I60 0.6899(ep2),
  权重 `logs/cnn_I{5,20,60}R{5,20,60}.pth`,样本 172万/84.8万/40.5万。
- 2024 弱、2025 强(尤其 I20 在 2024 几乎零收益),推测与市场环境有关,未验证。
- 2026.01~08(160 交易日,大盘走平)三组全哑火:I5-target100 -1.2% 勉强走平,I60 -5.6%,
  I20 -23.3% 垫底;只有 I5-target20 守住 +15.2%。短周期动量在震荡市鞭打最重,
  与主链路 2026 横评"MA40 门系全亏、裸奔版最硬"的结论方向一致。
  数据源:`Z:/test/train_data/train_data_v1_F60_20130101-20260831_*.parquet`,
  矩阵 `logs/ohlc_full_2026.npz`。
- 论文 H-L 多空与 A 股多头 target 不可直接比数字,仅方向性参考。

## 后续验证(2026-09,三路并行,结论:一正两负)
- 空仓门(MA20/MA60/VOL90,`src/gate_backtest.py`):**无效**。2026 18 个组合 17 个持平或更差
  (I5/MA60-t20 从 +4.9% 打到 -40.3%),2024/2025 牛市主升段被系统性踏空(I5-2024 t100
  +18%→+1~2%);"最优"VOL90 实质是几乎不触发(=无门)。震荡市中趋势门 47% 时间空仓,
  躲开的和错过的收益相抵后只剩损耗。产物 `logs/gate_2026/`。
- 对冲版(多 top + 空 bottom,`src/hedge_backtest.py`):**诊断性成立,不可直接执行**。
  I5-2026 t100 由 -0.01 转 **+0.48**/sharpe 0.06→2.37,证明 I5 排序两端同时有效;
  I20 部分转正(t20 -0.18→+0.06),I60 几乎不受益(底部无区分度)。但 A 股融券不可行,
  建议可执行用法是多头端"剔除 bottom"(负向过滤)而非市场中性产品。产物 `logs/hedge_2026/`。
- 环境切换(按 regime 选周期,`src/regime_analysis.py`):**不成立**。"趋势市→I20"是反的
  (趋势市赢家是 I60,两种波动状态都第一);唯一站得住的是"震荡→I60/空仓";
  预注册规则 R1(趋势上→I20、震荡→I60、趋势下→空仓)NAV 1.40,输给 I5 买持 +86.6%
  甚至略输市场 +45.1%。样本外仅 32 个月,结论按假设定级。产物 `logs/regime_2026/`。
- 综合:2026 唯一能赚钱的改法是 I5 + bottom 过滤(对冲验证的可执行版);门和切换都不用做。

## 四路抢救验证(2026-09,四子代理并行,全部证伪或边际)
- bottom 过滤(`src/bottom_filter.py`):**恒等变换,零作用**。top100 与 bottom500 在截面永不相交,
  N=100/200/500 与基线逐 bit 一致。利用 bottom 负向信号只能靠做空或改选择机制。
- 降频调仓(`src/lowfreq_backtest.py`):**净为负**。省费 ~1.4pp,代价是轮动损失 ~7~8pp;
  机制发现:损失不是持仓衰减(牛市信号保留率 95%+),而是错过新轮入 top 强票 + 踏空 8 月反弹。
  推荐维持逐日决策,控费靠 t20 集中。
- 高确信度加权(`src/conf_weight.py`):**尾部真实但兑现小**。prob 五分桶三年严格单调
  (2026 仅顶桶为正),但等权→加权仅 ±1~2pp 且胜者年际翻转。
- 波动率缩放(`src/vol_scale.py`):**不值得采用**。2024 牛市踏空 -17~-29pp,2026 sharpe 反而更差,
  8 月反转(vol 最高段恰是最肥鱼身)被系统性错过;只是把"0/1 鞭打"换成"0.4/0.6 踏空"。
- 附带实锤:去 8 月后 2026 t100 年化 -28.9%(t20 -21.7%),全年不亏全靠 8 月单月(+19.5%);
  +10bp 滑点下基线再掉 3~9pp 但全部排序不变。
- 最终结论:多头 target 框架内 2026 无解,唯一正收益是 I5-t20(+15.2%);抢救方向只剩做空/机制改,
  均超出当前框架,本系列验证到此收口。
