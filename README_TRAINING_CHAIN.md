# 训练链路说明（parquet -> per-code -> CNN）

> 交付时间：2026-09-01 01:24（冒烟训练已跑通）

## 1. 数据与环境

### 1.1 当前数据契约
- **源文件**：`/home/starcyan/code/quant/data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet` (3.5G, 11413377 行 × 58 列, 5166 股, 2013-01-04~2025-12-31)
- **已复制**：`cnn/data/test/train_data/train_data_v1_20130101-20251231_0faaf8c69c89.parquet`（同构，避免跨项目依赖）
- **Schema**：`code, kline_time, open/high/low/close/volume/amount/TOT_SHARE, is_trading` + 48 因子（见 `quant/scripts/export_training_data.py:EXPORT_FACTORS`）
  - 29 live(技术/量价) + 19 keep(估值/成长/质量/两融)，含 `gross_margin` 结构性缺席
   - 契约：`is_trading=False` 为合成行（OHLC/因子=NaN, volume/amount=0），训练侧必须过滤。
- **历史版本对比**：旧 39 列 (2.9G) → 新 58 列 (+19 财务/两融)，指纹 `0faaf8c69c89` 为最新

### 1.2 同构 uv 环境
- **量化环境**：`quant/pyproject.toml` / `requires-python >=3.12,<3.13` / `torch 2.13+cu126` / `AmazingData 1.1.8` + `tgw 1.0.8.7`
- **cnn 环境**：新建 `cnn/pyproject.toml` 完全复刻 quant 依赖（含本地 wheel 路径 `../quant/wheels/...`），`uv sync --offline` 已通过
- **Python**：`cnn/.python-version = 3.12`，`uv run --project . python --version => 3.12.13`
- **验证**：`uv run --project . python -c "import torch, pyarrow, pandas"` 均可，`torch.cuda.is_available()=True`

## 2. 链路设计

### 2.1 历史链路与当前链路
| 旧链路 | 新链路 |
|--------|--------|
| `processed_data_train/*.npz`（需手工多进程 `data_processor.py` 生成）| `data/test/train_data/*.parquet` 单文件直读 |
| 特征 8 维（历史 NPZ 实验）| parquet 原始集合含 48 因子；当前默认输出 `F=53`（52 raw feature `P18+R16+N12+G6` + 1 共享 `g9_observed_mask`），`F=69`（51+18 mask）与 `F=45`（39+6 mask）为历史 schema |
| 历史 close-close 标签 | 当前 open-open：`open[t+1+horizon]/open[t+1]-1`，horizon=5 |
| `NPZSequentialDataset` 历史缓存块 | `ParquetDataset` 按 code 分组、滑动窗口、per-code 归一化 |

> 旧 NPZ 训练链路和 close-close 实验只用于历史追溯，不得与当前 parquet/open-open 结果混用。

### 2.2 核心模块
- **`data/dataset.py`**：
  - `ParquetDataConfig`：`seq_len=60, horizon=5, bins=51边界/52类, normalize=per_code（默认，frozen 基线）, scaler_path=logs/scaler_per_code.pkl`；另支持 `--normalize relative`（E0，无状态）与 `--normalize rolling`（E2–E5，`--rolling_scope e0..e5`）
  - `ParquetDataset`：读取 parquet → 过滤 `is_trading=False` → 按 code 排序 → 计算 open-open future return → per-code 归一化 → 构建窗口索引
  - `create_dataloaders`：仅训练集 fit scaler 并落盘，验证集复用 `logs/scaler_per_code.pkl`（防泄露），支持时序切分
  - 默认输出：`x [53,60]`，其中 52 个 raw feature（`P→R→N→G` 顺序）加 1 个共享 `g9_observed_mask`；原始 48 因子集合不等于模型输入维度，`close` 已解禁进 P 组（relative 分母 `close[t-1]`）
- **`train.py`**：新训练入口，兼容 `Trainer` / `EMDLoss` / `LoggerManager`
  - 时序切分默认：训练 `2013-01-01~2023-12-31` (865万行) / 验证 `2024-01-01~2025-12-31` (245万行)
  - 模型默认：`CNNTransformer(featurenum=53, seq_len=60, num_classes=52, cnn_out_channels=128, d_model=256, nhead=8, layers=4)`；`featurenum` 以 `ParquetDataset.num_features=len(feature_cols_out)` 实测派生为权威
  - 训练：`AdamW(lr=3e-4, wd=1e-5)` + `EMDLoss(p=2, smooth)` + `ReduceLROnPlateau`

rolling 是 CNN 内的实验模式，不实现 quant exporter。`--rolling_scope e0..e5` 由 `data/rolling_scaler.py` `ROLLING_SCOPE_FEATURES`
派生：`e0=∅`、`e1/e2=P 组 18 列`、`e3=+volatility_5/10/20`、`e4=+volume_ratio_5/10/amihud`、`e5=+G9 *_raw 6`（滚动列数 0/18/18/21/24/30）；
入 scope 的 P 列 relative→252 滚动 robust，vol/volume/G 列 rolling winsor，非 scope 列按 `COLUMN_RULES`（R asinh / N clip01 / G fixed_clip）。
`close` 已解禁进 P 组（relative 分母 `close[t-1]`）。
validation 可使用 split 前最多 251 个有效交易日 context（frozen/relative 场景上限为 `seq_len-1`）；context 先经同一训练 scaler 变换，
**可进入滑动窗口作 warmup 输入，但绝不作为标签日、不产生样本标签**，标签日覆盖 = 区间交易日数 − `(horizon+1)`；
frozen/relative 与 rolling 的 state/schema/checkpoint identity 隔离。

### 2.3 兼容性修复（torch 2.13 + numpy 2.0 + py 3.12）
- `data/npz_data_load.py: DataConfig.bins` 改为 `field(default_factory=...)`（修复 mutable default 在 py3.12 的 ValueError）
- `training/early_stopping.py: np.Inf -> np.inf`（numpy 2.0 移除）
- `ReduceLROnPlateau(verbose=True)` 移除（torch 2.13 移除参数）

### 2.4 数据缓存（memmap）

- **位置**：`data/feature_cache.py`；缓存只落盘归一化**之后**的 `features`（float32）与小数组（标签/价格/时间），标签与价格保留真实精度。
- **开关**：`ParquetDataConfig.cache_enabled=False` 保冻结（单测/CI/评估脚本零改动）；`train.py` 训练入口默认开启，可用 `--no_cache` 关闭、`--rebuild_cache` 跳过命中并写新 generation。
- **缓存根解析优先级**：`--cache_dir` > 环境变量 `CNN_DATA_CACHE` > 平台默认。Linux：`$XDG_CACHE_HOME/cnn`（回退 `~/.cache/cnn`）；Windows：`%LOCALAPPDATA%\cnn\cache`（回退 `~/AppData/Local/cnn/cache`）。全程 `pathlib`，无盘符硬编码。
- **key 隔离维度**：parquet identity（路径/size/mtime/行数/schema digest）+ `role`（train/val）+ `mode`（relative/per_code/rolling）+ `rolling_scope`（e0..e5）+ `feature_cols`/`feature_cols_out` + scaler identity + `seq_len`/`horizon`/`max_windows_per_code`/`bins`，任一变化即不同 key，避免跨配置串缓存。
- **原子发布**：先在 `tmp-<pid>-<uuid>` 内顺序写数据 → `meta` → `.ok`，再 flush/close → `os.replace` 发布为新 generation 目录；读侧只认 `.ok`，未写完或异 key 一律 miss。重复写入递增 `-g<gen>`，**绝不覆盖在用目录**。
- **清理**：运行期不自动删除；清理只经显式模块级函数 `data.feature_cache.clear_cache(root, key)`。目录会随 generation 累积，需人工关注磁盘。
- **与 scaler 红线的关系**：缓存命中不改变归一化语义，也不削弱 `data/AGENTS.md` 的验证集红线——validation 命中仍须传入训练 scaler 并校验 identity/schema，缺 scaler 或 identity 不符照常报错，绝不重 fit。
- **验证命令**：
  ```bash
  uv run --project . python -m unittest tests.unit.data.test_feature_cache tests.unit.data.test_dataset_cache tests.unit.config.test_config_defaults
  uv run --project . python -m unittest discover tests/unit
  uv run --project . python -m data.dataset --max_codes 10 --normalize per_code
  # 指定 parquet（win32 共享盘示例路径）
  uv run --project . python -m data.dataset --parquet "Z:/test/train_data/train_data_v1_F60_20130101-20260831_26c3db036a26.parquet" --max_codes 10 --normalize per_code
  ```

## 3. 验证结果（冒烟）

### 3.1 命令
```bash
uv run --project . python train.py --smoke --num_workers 0
# 等价于：--max_codes 20 --epochs 1 --batch_size 256 --train 2013-2023 --val 2024-2025
```

### 3.2 日志
- **日志目录**：`logs/run_20260901_012401/`（含 `config.json`, `training.log`, `best_model.pth 15M`, `training_curve.png`, `confusion_matrix_*`）
- **数据集**：训练 49491 窗口 / 验证 8408 窗口（20股子集），该记录保留历史实验数字
- **模型**：该冒烟记录为历史 55 维输入实验；当前默认输入为 `[batch,53,60]` → 52 logits
- **训练**：194 batch/epoch, ~27s/epoch, `Train Loss 0.0641 Acc 0.0820 Val Loss 0.0600 Acc 0.0985`，`best_model.pth` 已保存并可加载推理
- **曲线**：`training_curve.png` 已生成

### 3.3 推理校验
```bash
uv run --project . python -c "
import torch; from models.cnn_transformer.config import ModelConfig; from models.cnn_transformer.model import CNNTransformer
m=CNNTransformer(ModelConfig(featurenum=53, seq_len=60, num_classes=52, cnn_out_channels=128, d_model=256, nhead=8, cnn_kernel_sizes=[1,3,5,7,10], num_encoder_layers=4, dropout_rate=0.3))
m.eval()
print(m(torch.randn(2,53,60)).shape)  # => torch.Size([2,52])
"
```

### 3.4 标签与回测时序

- 窗口长度为 `T=60`，窗口末日为 T 日决策日。
- 标签收益为 `open[t+1+horizon]/open[t+1]-1`，默认 `horizon=5`，即 T+1 open 到 T+6 open。
- `BINS` 有 51 个边界，`np.digitize` 产生 `C=52` 类。
- 回测使用 T 日预测排序，T+1 open 买入，T+6 open 卖出；标签收益和持仓收益必须保持同一 open-open 口径。
- **回测费用模型**（rolling 与 target 统一，`backtest/engine.py`）：买入佣金 `max(买额×0.00025, 5 元)`；卖出佣金 `max(卖额×0.00025, 5 元)` + 印花税 `卖额×0.00025`；单笔净收益 `(卖额−卖佣−印花税−买额−买佣)/(买额+买佣)`。`--capital`（默认 100 万）用于折算最低 5 元佣金。旧 `--cost_rate` 已废弃（显式传入仅告警并忽略）。
- **回测基准**：大盘指数 close-to-close（`--benchmark_index` 默认 `000300.SH` 沪深300，`--index_dir` 默认 `Z:/test/kline_index/day`）；超额 = 策略 annual − 指数 annual。旧「全截面等权」基准已弃用（`benchmark_nav` 仅测试保留）。
- **评估范围**：`--topn` 默认 `5 10 20`；target 模式默认 `sell_buffer=500`，可选 `--exit-on-nonpositive`（预测 exp_ret ≤ 0 即卖）。`metrics.json`/打印输出 `avg_cash_ratio`（rolling 恒 0；target 实测）。
- 训练 scaler fit 后保存为 `logs/scaler_per_code.pkl`，验证集复用该文件，禁止在验证集重新 fit。

## 4. 如何运行全量训练

### 4.1 小样本调试（推荐先跑）
```bash
uv run --project . python train.py --max_codes 100 --epochs 5 --batch_size 512 --num_workers 4
```

### 4.2 全量训练（5166 股，约 10M 窗口，需 ~8G 内存 + 5G 显存，单 epoch 约 20-30 分钟）
```bash
uv run --project . python train.py --epochs 50 --batch_size 256 --num_workers 4
# 或自定义时序切分
uv run --project . python train.py --train_start 2013-01-01 --train_end 2023-12-31 --val_start 2024-01-01 --val_end 2025-12-31 --epochs 50
```

### 4.3 仅训练集（无验证集，快速吞吐）
```bash
uv run --project . python train.py --no_val --epochs 10
```

### 4.4 数据集单独测试
```bash
uv run --project . python -m data.dataset --max_codes 20
uv run --project . python -m data.dataset --max_codes 100  # 更大数据
```

## 5. 文件清单

```
cnn/
  pyproject.toml  # 新增，与 quant 同构
  .python-version # 3.12
  data/
    test/train_data/train_data_v1_*.parquet  # 3.5G 已复制
    dataset.py  # 新增，核心数据集
  train.py  # 新增，直通训练入口
  training/early_stopping.py  # 修复 np.inf
  data/npz_data_load.py  # 修复 dataclass
  logs/
    scaler_per_code.pkl  # per-code 统计（训练集拟合，验证集复用）
    run_20260901_012401/  # 冒烟产物
  README_TRAINING_CHAIN.md  # 本文件
```

## 6. 后续建议
- **全量压测**：明日可跑 `max_codes 500` 进一步验证内存与速度，再切全量
- **特征选择**：48 是原始因子集合；当前默认输出 `F=53`（52 raw feature `P18+R16+N12+G6` + 1 共享 `g9_observed_mask`），`F=69`（51+18 mask）与 `F=45`（39+6 mask）仅用于历史记录，显式特征选择需单独记录维度
- **标签 horizon**：默认 5 日，可尝试 10/20 日对比
- **不平衡**：当前 52 类极不均衡（头部类占 <0.1%），可考虑 `class_weights` 或 `HalfClassWeightedCrossEntropy`
- **scaler 复用**：训练集 fit 后保存 `logs/scaler_per_code.pkl`，验证/推理侧务必复用同一文件
```
