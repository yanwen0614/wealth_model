# 保守特征训练计划

## 当前决定

- **主备选：B，F29 纯技术特征。** 沿用原 Parquet，只通过 `--feature_cols` 选择29列；不含5个未通过 PIT 的财务列、18个两融/G9列或 `g9_observed_mask`。
- **条件备选：A，F48。** 47个非财务 raw 特征加原生共享 mask。两融整体 PIT 审计结论交付且通过前，不训练、不比较。
- 先前提出的 F30 constant mask、18列置 NaN 派生 Parquet、独立 mask-source API 均已取消；无需生成派生文件。
- 当前只保留计划与 CPU 小样证据。未训练、未生成真实数据、未计算收益或 IC。W1 训练仍须等主会话取得技术29列审计结果并发出唯一许可。

## 特征清单

### B：主备选，F29

- P18：`open high low close ma_5 ma_10 ma_20 ma_60 ema_12 ema_26 sar trend_duokong trend_shortline macd std_5 std_10 std_20 atr`
- 技术 R11：`dmi adx boll kelch trend_duokong_dev volatility_5d volatility_10d volatility_20d volume_ratio_5d volume_ratio_10d amihud`
- 使用原始 Parquet，并关闭 cs-rank 与 market-factor 追加。`relative` scaler 不会在所选列不含 G9 源列时追加观测 mask。

### A：条件备选，F48

- 保留 B 的29列，再加两融 raw 特征18列：
- N12：`margin_balance_ratio margin_buy_ratio margin_net_buy_ratio margin_balance_chg_5d short_balance_ratio short_sell_vol_ratio margin_balance_ratio_ts margin_buy_ratio_ts margin_net_buy_ratio_ts margin_balance_chg_5d_ts short_balance_ratio_ts short_sell_vol_ratio_ts`
- G6：`margin_balance_ratio_raw margin_buy_ratio_raw margin_net_buy_ratio_raw margin_balance_chg_5d_raw short_balance_ratio_raw short_sell_vol_ratio_raw`
- 以上合计47 raw + 共享 mask = F48。两融已有 T+1/rolling20 源证据，但整体 PIT 产物仍有限；须待审计解决后才考虑。不默认优于 B，也不提前做收益选择。
- 排除财务列：`gross_margin net_margin roe roa debt_to_equity`。B 与 A 都不选择这5列。

## W3 基线核对与冻结项

- 依据 `logs/relative/run_20261026_032356/config.json` 与 `training.log`：30个总 epoch，AdamW，lr=3e-4，weight_decay=1e-5，CosineWarmup 预热3轮，patience=3，batch_size=1024，seed=42，num_workers=0；`seq_len=60`、H10、`label_mode=excess`、`normalize=relative`、模型 `cnn_transformer`。
- 同一 run config 记载 `CS_RANK=false`、`MKT_FACTORS=false`、`SAMPLE_WEIGHT=false`、`GATE_HEAD=false`；`DEVICE=cuda`（设备按现有程序自动配置）。
- W3 实际于第6/30轮早停，最佳零起点 epoch=2，val loss=0.057885。以上只用于固定训练设置，不表示本轮要训练。
- CLI parser 有 `--scheduler`、`--warmup_epochs`、`--lr`，没有 weight_decay CLI 参数；weight_decay 保留配置中的1e-5，不编造参数。命令显式指定 CosineWarmup，避免退回默认 Plateau。
- 保存配置中的损失为 EMD（p=2、label smoothing=true、smooth_eps=0.1）；CNNTransformer 为 128 CNN channels、d_model=256、nhead=8、4层、kernels `[1,3,5,7,10]`、dropout=0.3、52 classes。未提供对应 CLI 的参数保持当前已核实配置默认值。
- W3 原始 run config 的 `FEATURE_COLS` 为 null，实测输出 F53；本计划明确改传列子集，B 的 `feature_cols_out` 与 `featurenum` 均为29。
- 对照 W1 `run_20261025_203117/config.json`：训练 2013-01-01~2020-06-30、验证 2020-07-01~2020-12-31、`TEST_START=2026-01-01`、`TEST_END=null`。命令保留此测试预留；W3 的原测试预留是 2022H1。

## B 的 W1 命令模板（未执行，等待许可）

保留 W3 冻结超参与损失/模型默认值；只换 W1 日期、F29 列表、维度及独立缓存/运行身份。权重衰减取已保存配置值1e-5（无对应 CLI 参数）。PowerShell 命令如下：

```powershell
uv run --project . python train.py `
  --parquet C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet `
  --train_start 2013-01-01 --train_end 2020-06-30 --val_start 2020-07-01 --val_end 2020-12-31 `
  --test_start 2026-01-01 `
  --feature_cols open high low close ma_5 ma_10 ma_20 ma_60 ema_12 ema_26 sar trend_duokong trend_shortline macd std_5 std_10 std_20 atr `
    dmi adx boll kelch trend_duokong_dev volatility_5d volatility_10d volatility_20d volume_ratio_5d volume_ratio_10d amihud `
  --featurenum 29 --seq_len 60 --horizon 10 --normalize relative --rolling_scope e5 --label_mode excess `
  --model cnn_transformer --epochs 30 --patience 3 --batch_size 1024 --num_workers 0 --seed 42 --lr 3e-4 `
  --scheduler CosineWarmup --warmup_epochs 3 --no-cs_rank --no-mkt_factors `
  --cache_dir C:/Users/yanwen/AppData/Local/Temp/opencode/safe_feature_training_plan_probe/B_F29_W1_cache `
  --rebuild_cache
```

- `train.py` 根据当前时间戳建立独立 run 日志目录；缓存使用 F29 专属目录并强制新建 generation。未来实际运行须再记录代码 SHA/dirty、输入 Parquet SHA、run config 和缓存 key。
- F48 仍是条件方案：两融审计通过后，沿用此命令的 W1 日期和全部冻结超参，将 `--feature_cols` 换成前述 A 的47列、`--featurenum 48`，并使用独立 `A_F48_W1_cache`。这只是差异模板，不是当前训练许可。

## 已做 CPU 小样核验

- 复用 `safe_feature_training_plan_probe/mini_full_schema_g9_nan.parquet`，未重建 fixture；通过 `ParquetDataset` 实际加载，`relative`、`excess`、H10、seq_len=60，关闭缓存/cs-rank/market factors。
- 精确传入29个唯一特征名；实测 `feature_cols=29`、`feature_cols_out=29`、`num_features=29`、样本 tensor 形状 `[29, 60]`。
- 捕获 reader 实际投影的列：共32列（必要标识/标签列加29特征）；投影与输出均不含5个财务列、N12/G6两融列或 `g9_observed_mask`。断言全部通过。
- 使用 `train.parse_args` 按计划命令逐项解析：CLI_PARSE=PASS；检查了29列、维度、日期、W3 超参、scheduler 与关闭 cs/mkt flags。只解析参数，没有调用训练入口。
- 未读取真实大文件来做此验证；未启动训练、未生成或修改任何 Parquet、未比较预测结果。

## 资源与未决事项

- 源文件有12,254,385行，29个选中特征为 float64；全文件投影数值载荷约2.843 GB，转换成 F29 float32 全量上限约1.421 GB。均为载荷算术估算，不是峰值内存测量；临时拷贝、Arrow/Pandas开销及训练内存另计。
- Windows 16 GiB 主机沿用 `num_workers=0`。峰值资源与缓存盘占用尚未用全量 F29 运行测量。
- 技术29列的独立因果/PIT审计仍待 Luna 会话 `ses_e8a367a7bffeCV3DN0ERyQuYqd` 结论。主会话收到审计后会发唯一 F29 W1 许可；本会话不监控该会话。
- 标签口径、H10、序列长度、W1日期切分均保持冻结。reader 按 `end_date` 截断后计算标签，训练区间末尾每代码最后11行自然无 H10 标签；实际运行仍需记录有效标签日期与样本数。
- 历史窗口只用于探索，不构成独立样本外验收，也不能证明项目最终交易目标已达成。
