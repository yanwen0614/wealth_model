from glob import glob
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from numpy.lib.stride_tricks import sliding_window_view
import numpy as np
import logging
import os
import yaml
from typing import Optional, Dict, List, Tuple, Generator
from joblib import Parallel, delayed, cpu_count
import multiprocessing as mp

logger = logging.getLogger(__name__)

# ==================== 配置类 ====================

class DataPath:
    Kline_Snapshot_file_path: List[str] = []
    Share_Info: List[str] = []

    """数据路径配置"""
    def __init__(self, yaml_file: Optional[str] = None):
        """
        初始化数据路径配置
        
        Args:
            yaml_file: YAML配置文件路径，如果为None则使用默认配置
        """
        # 从YAML文件加载配置
        if yaml_file and os.path.exists(yaml_file):
            self._load_from_yaml(yaml_file)
        else:
            raise FileNotFoundError(f"YAML配置文件 {yaml_file} 不存在")
    
    def _load_from_yaml(self, yaml_file: str):
        """
        从YAML文件加载配置
        
        Args:
            yaml_file: YAML配置文件路径
        """
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if config:
                if 'Kline_Snapshot_file_path' in config:
                    self.Kline_Snapshot_file_path = self._ensure_list(config['Kline_Snapshot_file_path'])
                if 'Share_Info' in config:
                    self.Share_Info = self._ensure_list(config['Share_Info'])
                logger.info(f"从 {yaml_file} 加载数据路径配置成功")
        except Exception as e:
            logger.error(f"从 {yaml_file} 加载配置失败: {e}")
    
    def _ensure_list(self, value):
        """
        确保值为列表类型
        
        Args:
            value: 要检查的值
        
        Returns:
            列表类型的值
        """
        if isinstance(value, list):
            return value
        else:
            return [value]


# ==================== 核心数据处理类 ====================

class DataLoader:
    """数据加载器（合并原DataLoader功能）"""
    
    def __init__(self, data_path: DataPath, 
                 start_date: Optional[str] = None, 
                 end_date: Optional[str] = None):
        self.data_path = data_path
        self.start_date = start_date
        self.end_date = end_date
        self._load_data()
    
    def _load_data(self) -> None:
        """加载并预处理数据"""
        snapshots = []
        for file_path in self.data_path.Kline_Snapshot_file_path:
            if os.path.exists(file_path):
                snapshots.append(pd.read_parquet(file_path))
        if snapshots:
            snapshot = pd.concat(snapshots, ignore_index=True)
        else:
            logger.error("No valid Kline_Snapshot_file_path found")
            raise FileNotFoundError("No valid Kline_Snapshot_file_path found")

        
        # 转换时间格式
        snapshot["kline_time"] = pd.to_datetime(snapshot["kline_time"])
        
        # 时间过滤
        if self.start_date:
            snapshot = snapshot[snapshot["kline_time"] >= pd.to_datetime(self.start_date)]
        if self.end_date:
            snapshot = snapshot[snapshot["kline_time"] <= pd.to_datetime(self.end_date)]
        
        self.snapshot_dict = {k: v for k, v in snapshot.groupby("code")}
        

        share_infos = []
        for file_path in self.data_path.Share_Info:
            if os.path.exists(file_path):
                share_infos.append(pd.read_parquet(file_path))
        if share_infos:
            share_info = pd.concat(share_infos, ignore_index=True)
        else:
            logger.error("No valid Share_Info file found")
            raise FileNotFoundError("No valid Share_Info file found")

        
        self.share_info_dict = {k: v for k, v in share_info.groupby("MARKET_CODE")}
    
    def get__data(self, code: str) -> Optional[pd.DataFrame]:
        """获取单只的完整数据"""
        try:
            # 获取数据
            data = self.snapshot_dict.get(code)
            if data is None or data.empty:
                logger.info(f"{code} 无数据")
                return None
            if len(data) < 90:
                logger.info(f"{code} 数据过少 {len(data)}")
                return None
            
            data = data.sort_values("kline_time").copy()
            data["amp"] = data["close"].pct_change()
            data = data.dropna()
            
            # 合并信息
            share_info = self.share_info_dict.get(code)
            if share_info is None or share_info.empty:
                logger.warning(f"No share info for {code}")
                return None
            
            # 应用数据
            share_info = share_info.sort_values("EX_CHANGE_DATE")
            ex_dates = pd.to_datetime(share_info.EX_CHANGE_DATE).values
            float_shares = share_info.FLOAT_A_SHARE.values
            
            data["FLOAT_A_SHARE"] = data.apply(
                lambda t: self._get_float_share(t, ex_dates, float_shares)[1],
                axis=1
            )
            
            return data.reset_index(drop=True)
        except Exception as e:
            logger.error(f"{code} error {e}",exc_info=True)
            return None
    
    @staticmethod
    def _get_float_share(row: pd.Series, EX_CHANGE_DATE: List[pd.Timestamp], 
                        FLOAT_A_SHARE: List[float]) -> Tuple[pd.Timestamp, float]:
        """根据日期获取对应的流通A股数量"""
        last_t = EX_CHANGE_DATE[0]
        last_f = FLOAT_A_SHARE[0]
        
        if row.kline_time < last_t:
            return last_t, last_f
        
        for t, f in zip(EX_CHANGE_DATE[1:], FLOAT_A_SHARE[1:]):
            if row.kline_time >= last_t and row.kline_time < t:
                return last_t, last_f
            last_t, last_f = t, f
        
        return last_t, last_f


class DataProcessor:
    """数据处理器（使用joblib简化多进程处理）"""
    
    # 特征列定义
    RAW_COLS = ["kline_time", 'open', 'high', 'low', 'close', 
                "volume", "amount", 'FLOAT_A_SHARE', "amp"]
    FEATURE_COLS = ['open_normalized', 'high_normalized', 'low_normalized', 
                    'close_normalized', 'avg_price_normalized', 
                    'volume_normalized', 'volume_rate', "amp"]
    
    def __init__(self, loader: DataLoader,
                 window_size: int = 60,
                 predict_steps: int = 5,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 n_processes: Optional[int] = None):
        
        self.window_size = window_size
        self.predict_steps = predict_steps
        self.n_processes = n_processes or max(1, cpu_count() - 1)
        
        # 数据加载器
        self.loader = loader
        self.start_date = start_date
        self.end_date = end_date
        
        # 归一化器
        self.scaler = MinMaxScaler(feature_range=(-1, 1))
    
    def normalize_data(self, data: pd.DataFrame) -> Optional[pd.DataFrame]:
        """归一化数据"""
        try:
            data = data.copy()
            
            # 计算衍生特征
            data["avg_price"] = data["amount"] / data["volume"]
            data["volume_rate"] = data["volume"] / data["FLOAT_A_SHARE"]
            
            # 归一化价格列
            price_cols = ['open', 'high', 'low', 'close', 'avg_price']
            data[['open_normalized', 'high_normalized', 'low_normalized', 
                'close_normalized', 'avg_price_normalized']] = \
                self.scaler.fit_transform(data[price_cols])
            
            # 归一化成交量
            data['volume_normalized'] = self.scaler.fit_transform(data[['volume']])
            # raise RuntimeError("test")
            return data.dropna()
        except Exception as e:
            logger.error(f"error {e}", exc_info=True)
            return None
    
    def generate_samples(self, data: pd.DataFrame) -> Generator[
        Tuple[pd.Timestamp, np.ndarray, np.ndarray], None, None
    ]:
        """生成训练样本"""
        total_window = self.window_size + self.predict_steps
        slides = sliding_window_view(data[self.RAW_COLS].values, 
                                     window_shape=total_window, axis=0)
        
        for slide in slides:
            slide_df = pd.DataFrame(slide.T, columns=self.RAW_COLS)
            normalized = self.normalize_data(slide_df)
            if normalized is None:
                logger.error( f"normalize_data 出现错误 code  {data['code'].values[0]}")
                continue
            
            # 提取特征和标签
            features = normalized[self.FEATURE_COLS][:self.window_size].values.T
            labels = normalized[self.FEATURE_COLS][self.window_size:].values
            timestamp = slide_df["kline_time"].iloc[0]
            
            yield timestamp, features.astype(np.float32), labels.astype(np.float32)
    
    def save_to_numpy(self, output_dir: str = "processed_data",
                      max_s: Optional[int] = None,
                      max_samples_per_file: int = 50000,
                      batch_size: int = 10,
                      use_multiprocess: bool = True,
                      backend: str = 'loky') -> None:
        """
        保存处理后的数据（使用joblib简化）
        
        Args:
            output_dir: 输出目录
            max_s: 最大处理数
            max_samples_per_file: 每个文件最大样本数
            batch_size: 每批处理的数量
            use_multiprocess: 是否使用多进程
            backend: joblib后端 ('loky', 'multiprocessing', 'threading')
        """
        codes = list(self.loader.snapshot_dict.keys())
        if max_s:
            codes = codes[:max_s]
        
        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"Processing {len(codes)} s with "
                   f"{self.n_processes if use_multiprocess else 1} process(es), "
                   f"batch_size={batch_size}")
        
        if use_multiprocess:
            self._joblib_multiprocess_save(codes, output_dir, max_samples_per_file, 
                                          batch_size, backend)
        else:
            self._singleprocess_save(codes, output_dir, max_samples_per_file)
    
    def _joblib_multiprocess_save(self, codes: List[str], 
                                  output_dir: str, 
                                  max_samples: int,
                                  batch_size: int,
                                  backend: str) -> None:
        """
        使用joblib进行多进程处理（核心简化）
        
        优势：
        1. 自动进度条（verbose参数）
        2. 更简洁的语法
        3. 更好的内存管理
        4. 支持多种后端
        """
        # 将代码分组
        if "000918.SZ" in codes: codes.remove("000918.SZ")
        code_batches = self._split_into_batches(codes, batch_size)
        logger.info(f"Split {len(codes)} s into {len(code_batches)} batches")
        
        # 使用joblib并行处理
        # require='sharedmem' 可以减少内存复制（适用于大数据）
        results = Parallel(
            n_jobs=self.n_processes,
            backend=backend,
            verbose=10,  # 显示详细进度
            batch_size='auto'  # 自动批处理大小
        )(
            delayed(_process_batch_joblib)(
                batch_id, 
                batch_codes,
                self.data_path,
                self.start_date,
                self.end_date,
                self.window_size,
                self.predict_steps,
                output_dir,
                max_samples
            )
            for batch_id, batch_codes in enumerate(code_batches)
        )
        
        # 统计结果
        total_files = sum(r['files_saved'] for r in results if r)
        total_samples = sum(r['samples_processed'] for r in results if r)
        total_batches = len([r for r in results if r])
        
        logger.info(f"All data saved to {output_dir}/")
        logger.info(f"Total batches: {total_batches}, Total files: {total_files}, "
                   f"Total samples: {total_samples}")
    
    @staticmethod
    def _split_into_batches(codes: List[str], batch_size: int) -> List[List[str]]:
        """将代码列表分成若干组"""
        return [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    
    def _singleprocess_save(self, codes: List[str], 
                           output_dir: str, 
                           max_samples: int) -> None:
        """单进程处理并保存"""
        batch = {'codes': [], 'timestamps': [], 'features': [], 'labels': []}
        file_idx = 0
        
        # 使用joblib的tqdm集成
        from tqdm.auto import tqdm
        
        for code in tqdm(codes, desc="Processing s"):
            data = self.loader.get__data(code)
            if data is None:
                continue
            
            for timestamp, features, labels in self.generate_samples(data):
                batch['codes'].append(code)
                batch['timestamps'].append(timestamp)
                batch['features'].append(features)
                batch['labels'].append(labels)
                
                # 达到文件大小限制，保存
                if len(batch['codes']) >= max_samples:
                    self._save_batch(batch, output_dir, 0, file_idx)
                    batch = {'codes': [], 'timestamps': [], 
                            'features': [], 'labels': []}
                    file_idx += 1
        
        # 保存剩余数据
        if batch['codes']:
            self._save_batch(batch, output_dir, 0, file_idx)
    
    @staticmethod
    def _save_batch(batch: Dict, output_dir: str, 
                   batch_id: int, file_idx: int) -> None:
        """保存单个批次"""
        os.makedirs(output_dir, exist_ok=True)
        
        filename = f"{output_dir}/chunk_b{batch_id:04d}_{file_idx:04d}.npz"
        np.savez_compressed(
            filename,
            codes=np.array(batch['codes'], dtype=str),
            data_tags=np.array(batch['timestamps'], dtype='datetime64[ns]'),
            train_features=np.array(batch['features'], dtype=np.float32),
            labels=np.array(batch['labels'], dtype=np.float32)
        )
        
        logger.debug(f"Saved {filename} ({len(batch['codes'])} samples)")


# ==================== joblib工作函数 ====================

def _process_batch_joblib(batch_id: int,
                         batch_codes: List[str],
                         data_path: DataPath,
                         start_date: Optional[str],
                         end_date: Optional[str],
                         window_size: int,
                         predict_steps: int,
                         output_dir: str,
                         max_samples: int) -> Dict:
    """
    joblib工作函数（处理单个批次）
    
    Args:
        batch_id: 批次ID
        batch_codes: 该批次的代码列表
        data_path: 数据路径配置
        start_date: 开始日期
        end_date: 结束日期
        window_size: 窗口大小
        predict_steps: 预测步数
        output_dir: 输出目录
        max_samples: 每个文件最大样本数
    
    Returns:
        统计信息字典
    """
    try:
        # 创建数据加载器和处理器
        loader = DataLoader(data_path, start_date, end_date)
        processor = DataProcessor(data_path, window_size, predict_steps,
                                 start_date, end_date)
        
        # 批次缓存
        batch = {'codes': [], 'timestamps': [], 'features': [], 'labels': []}
        files_saved = 0
        samples_processed = 0
        file_idx = 0
        
        # 处理该批次的所有
        for code in batch_codes:
            data = loader.get__data(code)
            if data is None:
                continue
            
            # 生成样本
            for timestamp, features, labels in processor.generate_samples(data):
                batch['codes'].append(code)
                batch['timestamps'].append(timestamp)
                batch['features'].append(features)
                batch['labels'].append(labels)
                samples_processed += 1
                
                # 达到文件大小限制，保存
                if len(batch['codes']) >= max_samples:
                    DataProcessor._save_batch(batch, output_dir, batch_id, file_idx)
                    files_saved += 1
                    file_idx += 1
                    
                    # 重置批次
                    batch = {'codes': [], 'timestamps': [], 
                            'features': [], 'labels': []}
        
        # 保存剩余数据
        if batch['codes']:
            DataProcessor._save_batch(batch, output_dir, batch_id, file_idx)
            files_saved += 1
        
        return {
            'batch_id': batch_id,
            'files_saved': files_saved,
            'samples_processed': samples_processed
        }
    
    except Exception as e:
        logger.error(f"Error in batch {batch_id}: {e}", exc_info=True)
        return {
            'batch_id': batch_id,
            'files_saved': 0,
            'samples_processed': 0
        }


# ==================== 测试函数 ====================

def test_joblib_multiprocess():
    """测试joblib多进程处理"""
    processor = DataProcessor(
        end_date="2025-06-01",
        window_size=60,
        predict_steps=5,
        n_processes=23
    )
    
    processor.save_to_numpy(
        output_dir="processed_data_train",
        max_s=9999,
        max_samples_per_file=100000,
        batch_size=20,
        use_multiprocess=True,
        backend='multiprocessing'  # 或 'multiprocessing', 'threading'
    )


def val_data_multiprocess():
    """测试joblib多进程处理"""
    processor = DataProcessor(
        start_date="2025-07-01",
        window_size=60,
        predict_steps=5,
        n_processes=10
    )
    
    processor.save_to_numpy(
        output_dir="processed_data_val",
        max_s=9999,
        max_samples_per_file=500000,
        batch_size=100,
        use_multiprocess=True,
        backend='multiprocessing'  # 或 'multiprocessing', 'threading'
    )

def test_singleprocess():
    """测试单进程处理"""
    processor = DataProcessor(end_date="2025-06-01")
    
    processor.save_to_numpy(
        output_dir="processed_data_sp",
        max_s=10,
        max_samples_per_file=5000,
        use_multiprocess=False
    )


def test_data_loader():
    """测试数据加载器"""
    loader = DataLoader(DataPath(r"config\data_path.yaml"), start_date="2025-06-01")
    data = loader.get__data("000001.SZ")
    print(data[-10:])
    if data is not None:
        logger.info(f"Loaded data for 000001.SZ: {data.shape}")
    else:
        logger.warning("Failed to load data for 000001.SZ")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(processName)s -%(process)d - %(levelname)s - %(message)s'
)

if __name__ == "__main__":

    
    # 测试joblib多进程保存
    # val_data_multiprocess()
    
    # 或测试单进程
    # test_singleprocess()

    test_data_loader()