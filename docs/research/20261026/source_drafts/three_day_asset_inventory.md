# 三层自主研究资产盘点报告 v1.1

> 扫描时间: 2026-10-25 23:50 CST  
> 状态: **已终止扫描**, 后续源码溯源由 Sol session 负责  
> 报告路径: `C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_asset_inventory.json` (机器可读)

---

## 一、已验证事实

### 1.1 训练 Parquet

| 文件 | 路径 | 行数 | 代码数 | 时间范围 | 大小 |
|------|------|------|--------|----------|------|
| 主数据 | `C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet` | 12,254,385 | 5,199 | 2013-01-04 ~ 2026-08-31 | 4.28 GB |
| 旧数据 | `D:/code/cnn_full_20260905/cnn/data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet` | 11,413,377 | 5,166 | 2013-01-04 ~ 2025-12-31 | 3.68 GB |

**主数据事实:**
- **价格口径: 后复权 (backward-adjusted)**
  - 000001.SZ close: 355.05 (2013) → 1000.06 (2026)
  - 600519.SH close: 1085.87 (2013) → 10977.04 (2026)
- **成交量单位: 手 (lots of 100 shares)**
  - 与原始 kline 的 volume 比值恒为 0.01
- 含 `is_trading`、`TOT_SHARE`
- **不含**: adj_factor、industry、ST、suspended、FLOAT_A、FLOAT_SHARE
- 70 列: 10 基础 + 60 因子 (P18+R16+N12+G6 + 6 raw + 6 ts margin 衍生)

### 1.2 原始日线 Kline

| 路径 | 股票数 | 时间范围 | 示例 |
|------|--------|----------|------|
| `Z:/dev/kline/day/` | **5,215** (2903 SZ + 2312 SH) | 2013-01-04 ~ **2026-09-30** | 000001.SZ: 3336行 |

- Schema: `code, kline_time, open, high, low, close, volume, amount` (8列)
- 2026-09 后有 **21 交易日**数据 (2026-09-01 ~ 2026-09-30)
- **价格类型: 待确认** — 可见典型除权日跳变 (600519.SH 2014-06-25 -13.07%)
- **成交量/金额单位: 待确认** — amount/volume 比值约 16000×close (000001.SZ)
- 已在 `Z:/dev/kline/day/` 可读; 与训练 parquet volume 比值 = 0.01

### 1.3 指数 Parquet

- `Z:/dev/kline_index/day/` — **833 个指数**文件
- 沪深300: `000300.SH.parquet` — 3338行, 2013-01-04 ~ **2026-09-30**
- Schema: 同股票 (code, kline_time, o/h/l/c, volume, amount)
- **普通价格指数**, 可作约定基准; 全收益指数可作更严对照

### 1.4 预测缓存 NPZ

| 文件 | 大小 | 样本数 | 日期范围 | 字段 |
|------|------|--------|----------|------|
| `r4_excess_F53_preds_2026.npz` | 46.1MB | 768,549 | 2026-01-05 ~ 2026-08-14 (149天) | exp_ret,true_ret,dates,codes |
| `r4_excess_F53_preds_2025H2.npz` | 35.3MB | 587,867 | 2025-07-01 ~ 2025-12-16 | 同上 |
| `r4_excess_F53_preds_2021_2025.npz` | 338.2MB | 5,636,853 | 2021-01-04 ~ 2025-12-16 | 同上 |
| `w1_preds_2021H1.npz` | 25.2MB | 419,259 | 2021-01-04 ~ 2021-06-15 | 同上 |
| `w2_preds_2021H2.npz` | 28.5MB | 475,386 | 2021-07-01 ~ 2021-12-16 | 同上 |

**均不含 2026-09 后预测。**

### 1.5 Checkpoint

- **KEEP/baseline**: `logs/KEEP/baseline/best_model.pth` (15MB) — H=5, per_code, F=45, BINS=-0.25~0.25 (旧口径, **不建议直接复用**)
- **logs/relative/**: 2026-10-25 最新 excess+F53 训练 (run_20261025_223839 等)

### 1.6 树模型产物

- `logs/tree_rebuild/` — HGB/XGB main model predictions (2025 test/val)
- `logs/tree_verify/` — P1 cross-sectional, P2 rolling model predictions (12 files ~335MB)
- 结论: xgb_clf/EXT AUC=0.541, 方向预测弱于 always-long (0.553)

### 1.7 冻结脚本

- `scripts/frozen/` — 8 文件, READ_ONLY; 含旧 engine 回测和 XGB WF 脚本

---

## 二、待源码确认项 (已移交 Sol session)

| 项目 | 问题 | 核查路径 |
|------|------|----------|
| raw kline 价格类型 | 是原始不复权价还是前复权价 | 查 backtest 生产链路源码 |
| amount 单位 | amount/volume ≈ 16000×close | 查 parquet 生产者文档 |
| volume 单位 | 训练=手, 原始kline=股, ratio=0.01 | 确认原始列合约 |

---

## 三、执行验证关键缺口

| 缺口 | 影响 | 当前应对 |
|------|------|----------|
| 后复权→真实价格转换 | 成交金额/滑点/费用计算偏差 | 等 Sol 会话输出复权因子 |
| 分红送转数据 | 除权日持仓股数与市值不连续 | 暂无替代 |
| 2026-09 后训练特征 | 无法用完整9月数据重新训练 | 可用旧模型在原始日线上滚动构造特征推断 |

---

## 四、可用资产路径速查

```
# 训练数据 (后复权, 手)
C:/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet

# 原始日线 (类型/单位待确认, 至2026-09-30)
Z:/dev/kline/day/

# 指数基准 (至2026-09-30)
Z:/dev/kline_index/day/000300.SH.parquet

# 预测缓存 (仅至2026-08-14)
D:/tmp/opencode/r4_excess_F53_preds_2026.npz

# Checkpoint (旧KEEP基线)
D:/code/cnn_full_20260905/cnn/logs/KEEP/baseline/

# Checkpoint (最新excess+F53)
D:/code/cnn_full_20260905/cnn/logs/relative/run_20261025_223839/

# 审计脚本
D:/code/cnn_full_20260905/cnn/scripts/audit_walkforward_execution.py
```

---

## 五、扫描终止声明

- 当前会话 ses_e8c54700affe7HRtrHRvJJIFv3 已完成资产盘点
- 已停止全表/目录扫描, 释放 GPU/IO 资源给后续单窗训练
- 源码溯源移交 Sol session ses_e8c4943e0fferbkcOau03hZR63
- 报告写入: `C:/Users/yanwen/AppData/Local/Temp/opencode/three_day_asset_inventory.json` + 本 `.md`
