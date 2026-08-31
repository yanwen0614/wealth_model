import os
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from typing import List, Tuple
from dataclasses import dataclass
from .npz_data_load import NPZSequentialDataset,DataConfig


class NPZSequentialDataset2(NPZSequentialDataset):
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
                features:np.ndarray  = f["train_features"].astype(np.float32)
                labels:np.ndarray = f["labels"].astype(np.float32)
                labels:np.ndarray = np.sum(labels[:,:,-1],axis=1)
                discrete_labels = np.digitize(labels, self.config.bins)
                # print("features",features.shape)
                # print("labels",labels.shape)
                # print("discrete_labels",discrete_labels.shape)
            self.cache[path] = (features, discrete_labels)
        self.current_block_start = start_file_idx

    def __len__(self) -> int:
        return len(self.global_sample_idx)

if __name__ == "__main__":
    # python -m data.npz_data_load2
    """测试NPZ数据加载功能"""
    print("=== 测试NPZ数据加载功能 ===")
    
    # 1. 创建测试配置
    config = DataConfig(
        npz_dir="./processed_data_train",  # 测试数据目录
        cache_block_size=2,
        batch_size=50,
        num_workers=1,
        bins=(np.array(np.linspace(-30,30,61))/100).tolist()
    )


    # 3. 测试NPZSequentialDataset
    print("\n=== 测试NPZSequentialDataset ===")
    dataset = NPZSequentialDataset2(config)
    print("npz_files:", dataset.npz_files)
    print(f"数据集总样本数: {len(dataset)}")
    
    # 测试获取单个样本
    idx = np.random.randint(0, len(dataset))
    x, y = dataset[idx]
    print(f"单个样本形状 - features: {x.shape}, labels: {y}")
    print(f"标签值: {y.item()}")
    

        # 4. 测试DataLoader
    print("\n=== 测试DataLoader ===")
    dataloader = NPZSequentialDataset2.create_sequential_dataloader(config)

    
    print(f"DataLoader批次大小: {config.batch_size}")
    print(f"DataLoader迭代器长度: {len(dataloader)}")
    print("npz_files:", dataloader.dataset.npz_files)
    # 测试迭代DataLoader
    for batch_idx, (batch_x, batch_y) in enumerate(dataloader):
        print(f"批次 {batch_idx} - features形状: {batch_x.shape}, labels形状: {batch_y},当前缓存文件: {dataloader.dataset.cache.keys()}")
        break

