# 固定样本与文件证据

## HDF5固定样本

目录：`D:/code/quant/data/AmazingData_local_data/basedata/hist_stock_status/`。枚举到190个 `*.h5`；只完整读取以下8个代表文件以核字段和日期，不把此样本推算为全目录覆盖。

| 文件 | 总行数 | 2025行数/日期范围 | 当前文件SHA256 |
|---|---:|---|---|
| 000001.SZ.h5 | 2919 | 243，01-02至12-31 | f44140938d77d70d8215ad87a5db61276b4e51fbb79424e7e6431004644b72a7 |
| 000002.SZ.h5 | 2919 | 243，01-02至12-31 | 717e52f472329ebf59b315f39d7ef8d4399f2efac2c171e1837b53ba1adbbd15 |
| 000030.SZ.h5 | 2919 | 243，01-02至12-31 | 8ea778a107286c57d616412b1f49782da45ec60d44517b3da93d8b07041e722a |
| 000040.SZ.h5 | 2753 | 77，01-02至04-29 | e8e121860bf85cbc38061db33a37e1b7a7cba573300181ad109934b9e57af7c2 |
| 000045.SZ.h5 | 2919 | 243，01-02至12-31 | 504264a5a8d3e398e2e5ab55cac24e23f7e7503b1298facd9e81bb6c9074f42f |
| 000100.SZ.h5 | 2919 | 243，01-02至12-31 | 4648dffd2d6e27cce98a2473be658a2724cd7a1200d344d78d4208d70a70d170 |
| 000333.SZ.h5 | 2919 | 243，01-02至12-31 | 02850a1c8c6f1aa02c08db0ceb647aff68c9c15e65bec2bf0ee73fb3daaea1a6 |
| 000616.SZ.h5 | 2347 | 0，原文件止于2023-08-22 | 0be9a47bedf006aa7ad3b4d0ddfa396574abe1c60a04de277e07d744c14449b3 |

2025样本中出现243个日期；目标所称232日可能采用不同的交易日/评价窗口定义，本轮未构造目标日历，因此不作匹配判定。

## 安全边界与可复用清单

- `D:/code/quant/data/AmazingData_local_data/basedata/hist_code_list/20251231.pkl`：存在同名年末代码清单。未反序列化 pickle，避免执行不受信任的序列化内容；只能确认文件路径/命名，不能确认其代码数、内容或PIT性质。
- `Z:/dev/quant_data_dev.db`：只读连接，`history_status` schema和2025聚合见主报告；没有执行回写。
- `Z:/dev/kline/day/000001.SZ.parquet`：只读footer和schema抽查；仅行情OHLCV，不是绝对涨跌停界来源。
- `Z:/dev/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet`：只读Parquet footer/schema；不是状态来源。
- `state_acquisition_main_audit_20261027_v3/summary.json`：旧审计覆盖4,424码及其自身批次，不证明本目录190文件的来源、哈希绑定或2025覆盖。

## 隔离转换建议（本轮未执行）

在独立新目录执行单次只读转换：逐个读取190个HDF，筛选 `TRADE_DATE` 属于2025且目标交易日集合，统一为构建器字段（`market_code/trade_date_str/preclose/high_limited/low_limited/high_lmt_rate/low_lmt_rate/is_st_sec/is_susp_sec/is_wd_sec/is_xr_sec`）；保留原始字符串flag，不填补缺行；对每个输入HDF计算SHA256，并将相对路径与SHA写入本次隔离的source audit；对规范化11字段计算 `canonical_row_hash`，输出带 `code,date,row_hash,source_file_rel,source_sha256,sha_origin,window` 的Parquet及manifest。`sha_origin` 应标为本地现存缓存文件哈希，不能声称原始SDK源哈希。

建议调用形式（需先有隔离转换器，不是仓库现有命令）：`python convert_local_status_cache.py --input-root D:/code/quant/data/AmazingData_local_data/basedata/hist_stock_status --calendar <冻结日历> --output-root C:/Users/yanwen/AppData/Local/Temp/opencode/state_2025_local_inventory_20261029/cache --source-kind local_hdf_cache --no-source-write`。工作量为扫描/解码190个HDF、对读入源文件计算SHA并写一份Parquet和审计清单；精确耗时和体积未测，随缓存体积/磁盘速度变化。转换后结构上可满足构建器输入约定；缺少的代码/日期不得伪造，且盘前known_at与PIT宇宙依旧未知，因此不能单靠转换升格为完整可执行状态映射。
