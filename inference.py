import os

from tqdm import tqdm
# Set environment variable to avoid OpenMP conflict
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

import torch
import logging
import argparse
import json
import numpy as np
import pandas as pd
from data_processor import DataProcessor as OriginalDataProcessor, DataLoader as OriginalDataLoader, DataPath
from models.model2.model2 import CNNTransformer
from models.model2.config import ModelConfig
from log_manager import LoggerManager



class InferenceDataProcessor(OriginalDataProcessor):
    """精简版推理数据处理器，继承自 OriginalDataProcessor"""
    
    def __init__(self, loader: OriginalDataLoader,
                 window_size: int = 60,
                 start_date: str = None,
                 end_date: str = None,
                 n_processes: int = 1):
        """
        初始化推理数据处理器
        
        Args:
            data_path: 数据路径配置
            window_size: 窗口大小
            predict_steps: 预测步数
            start_date: 开始日期
            end_date: 结束日期
            n_processes: 进程数
        """
        # 调用父类初始化方法，传递所有参数
        super().__init__(
            loader=loader,
            window_size=window_size,
            predict_steps=5,  # 固定为5步预测
            start_date=start_date,
            end_date=end_date,
            n_processes=n_processes
        )
        # 转换日期格式，确保使用 pandas.Timestamp 类型
        self.start_date = pd.to_datetime(start_date) if start_date else None
        self.end_date = pd.to_datetime(end_date) if end_date else None
    
    def generate_inference_samples(self, data: pd.DataFrame) -> tuple:
        """生成推理样本"""
        samples = []
        timestamps = []
        
        if len(data) < self.window_size:
            logging.warning(f"数据长度不足 {len(data)} < {self.window_size}")
            return samples, timestamps
        
        # 确保数据按时间排序
        sorted_data = data.sort_values(by="kline_time").copy()
        start_index = sorted_data["kline_time"].searchsorted(self.start_date) if self.start_date else 0
        end_index = sorted_data["kline_time"].searchsorted(self.end_date, side='right') if self.end_date else len(sorted_data)
        sorted_data = sorted_data.iloc[start_index-self.window_size+1:end_index]
        
        # 生成滑动窗口样本
        for i in range(len(sorted_data) - self.window_size + 1):
            # 提取滑窗数据
            window_data = sorted_data.iloc[i:i+self.window_size]
            # 使用父类的归一化方法
            normalized = self.normalize_data(window_data)
            if normalized is None:
                continue
            
            # 提取特征和时间戳
            features = normalized[self.FEATURE_COLS].values.T.astype(np.float32)
            timestamp = window_data["kline_time"].iloc[-1]
            
            # 检查时间范围
            if (not self.start_date or timestamp >= self.start_date) and \
               (not self.end_date or timestamp <= self.end_date):
                samples.append(features)
                timestamps.append(timestamp)
        
        # 记录生成结果
        if not samples:
            logging.warning(f"在指定的时间范围内没有生成任何样本")
        else:
            logging.debug(f"成功生成 {len(samples)} 个推理样本")
        
        return samples, timestamps


def main(config):
    """主程序入口函数"""
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description='推理CNNTransformer模型')
    parser.add_argument('--model_path', type=str, default=config.get('inference_model_path'), help='模型路径')
    parser.add_argument('--codes', type=str, nargs='+', default=config.get('codes', []), help='要推理的代码列表')
    parser.add_argument('--start_date', type=str, default=config.get('start_date'), help='开始日期')
    parser.add_argument('--end_date', type=str, default=config.get('end_date'), help='结束日期')
    args = parser.parse_args()
    
    # 更新配置
    config['inference_model_path'] = args.model_path
    config['codes'] = args.codes
    config['start_date'] = args.start_date
    config['end_date'] = args.end_date
    
    # 2. 初始化日志系统
    logger_manager = LoggerManager(config=config)
    logger = logging.getLogger(__name__)
    logger.info("=== 推理开始 ===")
    config["run_log_dir"] = logger_manager.run_log_dir
    
    # 3. 初始化数据加载器和处理器
    logger.info("=== 初始化数据加载器 ===")
    data_loader = OriginalDataLoader(data_path=DataPath(config['data_path_yaml']))
    data_processor = InferenceDataProcessor(
        loader=data_loader,
        window_size=config['SEQ_LEN'],
        start_date=config['start_date'],
        end_date=config['end_date'],
        n_processes=1  # 推理通常使用单进程
    )
    
    # 4. 模型初始化
    logger.info("=== 初始化模型 ===")
    
    # 创建模型配置
    model_config = ModelConfig(
        featurenum=config['INPUT_DIM'],
        seq_len=config['SEQ_LEN'],
        num_classes=config['NUM_CLASSES'],
        cnn_out_channels=config['CNN_OUT_CHANNELS'],
        d_model=config['D_MODEL'],
        nhead=config['NHEAD'],
        num_encoder_layers=config['NUM_ENCODER_LAYERS'],
        dropout_rate=config['DROPOUT_RATE']
    )
    
    # 创建模型
    model = CNNTransformer(model_config).to(config['DEVICE'])
    model_path = config["inference_model_path"]
    model.load_state_dict(torch.load(model_path, map_location=config['DEVICE']))
    logger.info(f"加载最佳模型完成: {model_path}")
    
    # 6. 推理
    logger.info("=== 开始推理 ===")
    
    model.eval()
    
    # 保存结果的目录
    results_dir = os.path.join(config["run_log_dir"], "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # 创建CSV文件并准备流式写入
    csv_file_path = os.path.join(results_dir, "predictions.csv")
    csv_file = None
    csv_writer = None
    total_predictions = 0
    
    # 如果没有指定代码，使用所有代码
    if not config['codes']:
        config['codes'] = list(data_loader.snapshot_dict.keys())
    
    logger.info(f"开始处理 {len(config['codes'])} 个代码")
    
    try:
        # 生成类值映射：第0类对应-0.305，间隔0.01
        class_values = [-0.305 + i * 0.01 for i in range(config['NUM_CLASSES'])]
        # 批量推理
        for code_idx, code in tqdm(enumerate(config['codes']), desc="处理进度",total=len(config['codes'])):

            # 加载数据
            data = data_loader.get__data(code)
            if data is None:
                logger.warning(f"代码 {code} 的数据加载失败，跳过")
                continue
            
            # 生成样本
            samples, timestamps = data_processor.generate_inference_samples(data)
            if not samples:
                logger.warning(f"代码 {code} 在指定时间范围内没有生成任何样本，跳过")
                continue
            
            with torch.no_grad():
  
                # 转换为tensor
                input_tensor = torch.tensor(samples, dtype=torch.float32).to(config['DEVICE'])
                
                # 前向传播
                outputs = model(input_tensor)
                import torch.nn.functional as F
                probs = F.softmax(outputs, dim=1).to('cpu').numpy().tolist()
                max_class_indices = np.argmax(probs, axis=1)
                for idx, (timestamp, probs, max_class_idx) in enumerate(zip(timestamps, probs, max_class_indices)):
                    # 构建结果字典
                    res = {
                        'code': code,
                        'timestamp': timestamp,
                        'max_class_idx': max_class_idx,
                    }
                    
                    # 计算概率分布的期望
                    expected_value = sum(value * prob for value, prob in zip(class_values, probs))
                    res['expected_value'] = expected_value
                    if abs(expected_value) > 0.10 or abs(max_class_idx-30) > 15:
                        logger.info(f"代码 {code} 在时间戳 {timestamp} 的期望值为 {expected_value}, 最大类索引为 {max_class_idx}, class_values {class_values[max_class_idx]}")
                    else:
                        logger.debug(f"代码 {code} 在时间戳 {timestamp} 的期望值为 {expected_value}, 最大类索引为 {max_class_idx}, class_values {class_values[max_class_idx]}")
                    
                    for class_idx in range(config['NUM_CLASSES']):
                        res[f'class_prob_{class_idx}'] = probs[class_idx]
                    
                    # 流式写入CSV文件
                    if not csv_file:
                        csv_file = open(csv_file_path, 'w', newline='', encoding='utf-8')
                        # 构建表头
                        fieldnames = ['code', 'timestamp','max_class_idx', 'expected_value'] + [f'class_prob_{idx}' for idx in range(config['NUM_CLASSES'])]
                        import csv
                        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                        csv_writer.writeheader()
                
                    # 写入当前结果
                    csv_writer.writerow(res)
                    total_predictions += 1
                    
                    # 每1000个预测结果刷新一次文件
                    if total_predictions % 1000 == 0:
                        csv_file.flush()
                        logger.debug(f"已写入 {total_predictions} 个预测结果")

                
                # for i, (features, timestamp) in enumerate(zip(samples, timestamps)):
                #     # 转换为tensor并添加batch维度
                #     input_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0).to(config['DEVICE'])
                    
                #     # 前向传播
                #     outputs = model(input_tensor)
                #     import torch.nn.functional as F
                #     probs = F.softmax(outputs, dim=1).to('cpu').numpy().tolist()[0]
                    
                #     # 生成类值映射：第0类对应-0.305，间隔0.01
                #     class_values = [-0.305 + i * 0.01 for i in range(config['NUM_CLASSES'])]
                    
                #     # 构建结果字典
                #     res = {
                #         'code': code,
                #         'timestamp': timestamp,
                #     }
                    
                #     # 计算概率分布的期望
                #     expected_value = sum(value * prob for value, prob in zip(class_values, probs))
                #     res['expected_value'] = expected_value
                    
                #     for class_idx in range(config['NUM_CLASSES']):
                #         res[f'class_prob_{class_idx}'] = probs[class_idx]
                    
                #     # 流式写入CSV文件
                #     if not csv_file:
                #         csv_file = open(csv_file_path, 'w', newline='', encoding='utf-8')
                #         # 构建表头
                #         fieldnames = ['code', 'timestamp', 'expected_value'] + [f'class_prob_{idx}' for idx in range(config['NUM_CLASSES'])]
                #         import csv
                #         csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
                #         csv_writer.writeheader()
                #         header_written = True
                    
                #     # 写入当前结果
                #     csv_writer.writerow(res)
                #     total_predictions += 1
                    
                #     # 每1000个预测结果刷新一次文件
                #     if total_predictions % 1000 == 0:
                #         csv_file.flush()
                #         logger.info(f"已写入 {total_predictions} 个预测结果")
    finally:
        # 关闭文件
        if csv_file:
            csv_file.close()
    
    # 7. 保存结果
    logger.info("=== 保存推理结果 ===")
    
    if total_predictions > 0:
        logger.info(f"推理结果已保存到: {csv_file_path}")
        logger.info(f"共生成 {total_predictions} 个预测结果")
    else:
        logger.warning("未生成任何预测结果")
    
    # 8. 推理结束
    logger.info("=== 推理结束 ===")


if __name__ == "__main__":
    # 加载配置
    if os.path.exists("logs/baseline/config.json"):
        config = json.load(open("logs/baseline/config.json", "r"))
    else:
        # 默认配置
        config = {
            'DEVICE': 'cuda' if torch.cuda.is_available() else 'cpu',
            'INPUT_DIM': 8,
            'SEQ_LEN': 60,
            'NUM_CLASSES': 9,
            'CNN_OUT_CHANNELS': 64,
            'D_MODEL': 128,
            'NHEAD': 8,
            'NUM_ENCODER_LAYERS': 3,
            'DROPOUT_RATE': 0.2,
            'codes': [],  # 默认处理所有代码
            'start_date': None,
            'end_date': None
        }
    
    # 设置默认模型路径
    config["DEVICE"] = "cuda" if torch.cuda.is_available() else "cpu"
    config["inference_model_path"] = os.path.join("logs/baseline/", "best_model.pth")
    config["data_path_yaml"] = "config/data_path.yaml"
    # config["codes"] = ["000001.SZ"]
    config["start_date"] = "2026-01-01"
    config["end_date"] = "2026-02-28"
    
    main(config)