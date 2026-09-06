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
| 特征 8 维（历史 NPZ 实验）| parquet 原始集合含 48 因子；当前 per-code 默认输出 `F=45`（39 有效特征+6 G9 mask）|
| 历史 close-close 标签 | 当前 open-open：`open[t+1+horizon]/open[t+1]-1`，horizon=5 |
| `NPZSequentialDataset` 历史缓存块 | `ParquetDataset` 按 code 分组、滑动窗口、per-code 归一化 |

> 旧 NPZ 训练链路和 close-close 实验只用于历史追溯，不得与当前 parquet/open-open 结果混用。

### 2.2 核心模块
- **`data/dataset.py`**：
  - `ParquetDataConfig`：`seq_len=60, horizon=5, bins=51边界/52类, normalize=per_code, scaler_path=logs/scaler_per_code.pkl`
  - `ParquetDataset`：读取 parquet → 过滤 `is_trading=False` → 按 code 排序 → 计算 open-open future return → per-code 归一化 → 构建窗口索引
  - `create_dataloaders`：仅训练集 fit scaler 并落盘，验证集复用 `logs/scaler_per_code.pkl`（防泄露），支持时序切分
  - 默认输出：`x [45,60]`，其中 39 个有效特征加 6 个 G9 mask；原始 48 因子集合不等于模型输入维度
- **`train.py`**：新训练入口，兼容 `Trainer` / `EMDLoss` / `LoggerManager`
  - 时序切分默认：训练 `2013-01-01~2023-12-31` (865万行) / 验证 `2024-01-01~2025-12-31` (245万行)
  - 模型默认：`CNNTransformer(featurenum=45, seq_len=60, num_classes=52, cnn_out_channels=128, d_model=256, nhead=8, layers=4)`
  - 训练：`AdamW(lr=1e-4, wd=1e-5)` + `EMDLoss(p=2, smooth)` + `ReduceLROnPlateau`

### 2.3 兼容性修复（torch 2.13 + numpy 2.0 + py 3.12）
- `data/npz_data_load.py: DataConfig.bins` 改为 `field(default_factory=...)`（修复 mutable default 在 py3.12 的 ValueError）
- `training/early_stopping.py: np.Inf -> np.inf`（numpy 2.0 移除）
- `ReduceLROnPlateau(verbose=True)` 移除（torch 2.13 移除参数）

## 3. 验证结果（冒烟）

### 3.1 命令
```bash
uv run --project . python train.py --smoke --num_workers 0
# 等价于：--max_codes 20 --epochs 1 --batch_size 256 --train 2013-2023 --val 2024-2025
```

### 3.2 日志
- **日志目录**：`logs/run_20260901_012401/`（含 `config.json`, `training.log`, `best_model.pth 15M`, `training_curve.png`, `confusion_matrix_*`）
- **数据集**：训练 49491 窗口 / 验证 8408 窗口（20股子集），该记录保留历史实验数字
- **模型**：该冒烟记录为历史 55 维输入实验；当前默认输入为 `[batch,45,60]` → 52 logits
- **训练**：194 batch/epoch, ~27s/epoch, `Train Loss 0.0641 Acc 0.0820 Val Loss 0.0600 Acc 0.0985`，`best_model.pth` 已保存并可加载推理
- **曲线**：`training_curve.png` 已生成

### 3.3 推理校验
```bash
uv run --project . python -c "
import torch; from models.cnn_transformer.config import ModelConfig; from models.cnn_transformer.model import CNNTransformer
m=CNNTransformer(ModelConfig(featurenum=45, seq_len=60, num_classes=52, cnn_out_channels=128, d_model=256, nhead=8, cnn_kernel_sizes=[1,3,5,7,10], num_encoder_layers=4, dropout_rate=0.3))
m.eval()
print(m(torch.randn(2,45,60)).shape)  # => torch.Size([2,52])
"
```

### 3.4 标签与回测时序

- 窗口长度为 `T=60`，窗口末日为 T 日决策日。
- 标签收益为 `open[t+1+horizon]/open[t+1]-1`，默认 `horizon=5`，即 T+1 open 到 T+6 open。
- `BINS` 有 51 个边界，`np.digitize` 产生 `C=52` 类。
- 回测使用 T 日预测排序，T+1 open 买入，T+6 open 卖出；标签收益和持仓收益必须保持同一 open-open 口径。
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
- **特征选择**：48 是原始因子集合；当前默认 per-code 输出 F=45（39 有效特征+6 G9 mask），显式特征选择需单独记录维度
- **标签 horizon**：默认 5 日，可尝试 10/20 日对比
- **不平衡**：当前 52 类极不均衡（头部类占 <0.1%），可考虑 `class_weights` 或 `HalfClassWeightedCrossEntropy`
- **scaler 复用**：训练集 fit 后保存 `logs/scaler_per_code.pkl`，验证/推理侧务必复用同一文件
```
