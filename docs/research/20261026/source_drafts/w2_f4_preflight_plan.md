# W2 F4 训练启动预检

- Worktree: `C:\Users\yanwen\.local\share\opencode\worktree\a2c2dea9fdaf0d6b75806767edcddf5ed61bc2f1\w2-f4-training-20261026`
- W1: `D:\code\cnn_full_20260905\cnn\logs\relative\run_20261026_100509`
- W1 配置/checkpoint：4列 open/high/low/close，relative，seq=60，H10，excess，52类；CNNTransformer F4/d_model256/nhead8/4层/kernels[1,3,5,7,10]/dropout0.3；30 epoch，CosineWarmup3，AdamW lr=3e-4/wd=1e-5，patience3，batch1024，workers0，seed42。checkpoint epoch=1，配置相同。
- W1 日期实际为 train 2013-01-01~2020-06-30、val 2020-07-01~2020-12-31；本次按授权窗口 train 2013-01-01~2020-12-31、val 2021-01-01~2021-06-30。
- 数据源：`C:\train_data\train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`；W1 记录 12,254,385 行、4,279,965,200 bytes、schema SHA256 `935180d7d030c4ccdfbd784788a9563a95e545dfd8f1d3b0aab5b6f78de7ae18`、父 SHA256 `9125DA792BB906EB3D31A82649EFA4358274FEC2B59F1DC911F7C71871910741`。不重算父哈希。
- 小样已确认首末日期为 2013-01-04 / 2026-08-31，parquet 有 kline_time/code/OHLC/is_trading。当前环境私有 `.venv` Python/Torch 路径在本 worktree，torch 2.12.0+cu130，CUDA=True。
- 当前源码只读 SHA256：train.py `4EB066D9BEF370809C50B48889ABE9F613FA6EC16127BAEE540160134C995EAD`；dataset.py `6B9325B33942DC78B9BF6967E4DE07C52C397A4D313ED44FFF16911523FA9A56`；reader.py `DD8338C95C508110634E39D5B1B91F1C6D4B030F7E33156CCA2605A1B3B58D00`；scaler.py `9A2FCBC5739BA4517C1210BCFAC2973FDB3A790E656C8562531E7BFCA5CB4136`。
- Cache root 独占：`<worktree>\w2_f4_cache`；run logs/checkpoint：`<worktree>\logs\run_*`；console/stdout resource evidence 存本 worktree。
- CLI：`uv run --offline --no-sync --project <worktree> python train.py --parquet C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet --train_start 2013-01-01 --train_end 2020-12-31 --val_start 2021-01-01 --val_end 2021-06-30 --feature_cols open high low close --featurenum 4 --normalize relative --seq_len 60 --horizon 10 --label_mode excess --no-cs_rank --no-mkt_factors --epochs 30 --scheduler CosineWarmup --warmup_epochs 3 --lr 0.0003 --patience 3 --batch_size 1024 --num_workers 0 --seed 42 --cache_dir <worktree>\w2_f4_cache --rebuild_cache`
- `--weight_decay` 不存在于 CLI；本 worktree 默认配置为 1e-5，与 W1 checkpoint/config 一致。启动前需核对 runtime config。启动前可用 RAM 下限 2.5 GiB；运行期间持续单进程采样，低于阈值即停止并留证，不重启或调参。
