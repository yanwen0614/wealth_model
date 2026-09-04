import os
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from typing import List, Tuple
from dataclasses import dataclass, field
from tqdm import tqdm

@dataclass
class DataConfig:
    npz_dir: str = "/path/to/your/npz_files"  # npz文件存放目录
    cache_block_size: int = 10                # 一次预加载的连续npz文件数（150G内存可设为20）
    batch_size: int = 512                     # 批次大小
    num_workers: int = 4                     # 数据加载进程数
    bins: np.ndarray = field(default_factory=lambda: np.array([-15, -7, -3, -1, 1, 3, 7, 15]) / 100)


class NPZSequentialDataset(Dataset):
    """
    顺序读取的NPZ数据集,内部 shuffle
    """
    def __init__(
        self,
        config: DataConfig,
    ):
        self.config = config
        
        # 1. 按时序顺序排序所有npz文件
        self.npz_files = sorted([f for f in os.listdir(config.npz_dir) if f.endswith(".npz")])
        np.random.shuffle(self.npz_files)
        self.load_meta()


    def load_meta(self):
        self.active_paths = [os.path.join(self.config.npz_dir, f) for f in self.npz_files]
        
        
        # 3. 预统计每个文件的样本数，构建全局样本索引
        self.global_sample_idx = []
        self.file_sample_counts = []
        for path in tqdm(self.active_paths,desc="load npz index"):
            with np.load(path, mmap_mode="r") as f:
                n_samples = f["labels"].shape[0]
                self.file_sample_counts.append(n_samples)
                self.global_sample_idx.extend([(path, i) for i in range(n_samples)])
        
        # 4. 初始化内存缓存（预加载第一个数据块）
        self.cache = {}  # key: npz路径, value: (features, labels)
        self._preload_next_block(0)


    def _preload_next_block(self, start_file_idx: int):
        """预加载连续的cache_block_size个文件到内存"""
        # 清理过期缓存
        self.cache.clear()
        # 预加载连续文件
        end_idx = min(start_file_idx + self.config.cache_block_size, len(self.active_paths))
        for i in range(start_file_idx, end_idx):
            path = self.active_paths[i]
            with np.load(path) as f:
                # 一次性加载整个文件到内存
                features = f["train_features"].astype(np.float32)
                labels = f["labels"].astype(np.int64)
            self.cache[path] = (features, labels)
        self.current_block_start = start_file_idx

    def __len__(self) -> int:
        return len(self.global_sample_idx)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        path, sample_idx = self.global_sample_idx[idx]
        # 检查当前文件是否在缓存中，不在则预加载对应块
        if path not in self.cache:
            file_idx = self.active_paths.index(path)
            self._preload_next_block(file_idx // self.config.cache_block_size * self.config.cache_block_size)
        
        # 从缓存中读取数据
        features, labels = self.cache[path]
        # print("features[sample_idx]",features[sample_idx])
        # print("labels[sample_idx]",labels[sample_idx])
        x = torch.from_numpy(features[sample_idx])
        y = torch.tensor(labels[sample_idx])
        return x, y

    @classmethod
    def create_sequential_dataloader(cls,
        config: DataConfig,
    ) -> DataLoader:
        """创建顺序读取的DataLoader（不shuffle）"""
        dataset = cls(config)
        return DataLoader(
            dataset,
            batch_size=config.batch_size,
            shuffle=False, 
            num_workers=config.num_workers,
            pin_memory=True,
            prefetch_factor=2,  # 顺序读取放大预取数
            persistent_workers=True  # 保持worker进程，避免epoch间重新初始化
        )


if __name__ == "__main__":
    # python -m data.npz_data_load
    """测试NPZ数据加载功能"""
    print("=== 测试NPZ数据加载功能 ===")
    
    # 1. 创建测试配置
    config = DataConfig(
        npz_dir="./test_npz_data",  # 测试数据目录
        cache_block_size=2,
        batch_size=50,
        num_workers=1
    )
    
    # 2. 创建测试数据（如果不存在）
    if not os.path.exists(config.npz_dir):
        os.makedirs(config.npz_dir)
        print(f"创建测试数据目录: {config.npz_dir}")
        
        # 生成3个测试npz文件
        for i in range(5):
            num_samples = 100 + i * 50
            features = np.random.randn(num_samples, 10, 20).astype(np.float32)  # (样本数, 特征数, 序列长度)
            labels = np.random.randint(0, 5, size=num_samples).astype(np.int64)  # 5分类
            
            npz_path = os.path.join(config.npz_dir, f"test_data_{i:03d}.npz")
            np.savez(npz_path, train_features=features, labels=labels)
            print(f"生成测试文件: {npz_path}，样本数: {num_samples}")
    
    # 3. 测试NPZSequentialDataset
    print("\n=== 测试NPZSequentialDataset ===")
    dataset = NPZSequentialDataset(config)
    print("npz_files:", dataset.npz_files)
    print(f"数据集总样本数: {len(dataset)}")
    
    # 测试获取单个样本
    idx = np.random.randint(0, len(dataset))
    x, y = dataset[idx]
    print(f"单个样本形状 - features: {x.shape}, labels: {y}")
    print(f"标签值: {y.item()}")
    
    # 测试缓存机制
    print("\n=== 测试缓存机制 ===")
    # 访问不同文件的样本，触发缓存预加载
    for i in range(0, len(dataset), 200):
        x, y = dataset[i]
        print(f"访问样本 {i}，当前缓存文件: {dataset.cache.keys()}, ")
    
    # 4. 测试DataLoader
    print("\n=== 测试DataLoader ===")
    dataloader = create_sequential_dataloader(config)
    print(f"DataLoader批次大小: {config.batch_size}")
    print(f"DataLoader迭代器长度: {len(dataloader)}")
    print("npz_files:", dataloader.dataset.npz_files)
    # 测试迭代DataLoader
    for batch_idx, (batch_x, batch_y) in enumerate(dataloader):
        print(f"批次 {batch_idx} - features形状: {batch_x.shape}, labels形状: {batch_y},当前缓存文件: {dataloader.dataset.cache.keys()}")

