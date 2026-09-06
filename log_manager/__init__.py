import logging
import os
import sys
from datetime import datetime
import json

class LoggerManager:
    """
    日志管理器类
    职责：配置日志系统，支持同时输出到控制台和文件
    
    参数:
        log_dir: 日志根目录
        config: 配置管理器实例（可选）
    """
    def __init__(self, log_dir: str = "logs", config = None):
        self.log_dir = log_dir
        self.config = config
        
        # 创建带时间戳的日志文件夹
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_log_dir = os.path.join(log_dir, f"run_{self.timestamp}")
        
        # 创建日志目录
        os.makedirs(self.run_log_dir, exist_ok=True)
        
        # 配置日志系统
        self._configure_logging()
        
        # 持久化配置（如果提供了配置）
        if self.config:
            self._save_config()
    
    def _configure_logging(self):
        """配置日志系统"""
        # 清除已有的日志处理器
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)
        
        # 日志格式
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        formatter = logging.Formatter(log_format)
        
        # 配置根日志记录器
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 文件处理器
        log_file = os.path.join(self.run_log_dir, "training.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # 记录日志初始化信息
        logger.info(f"日志系统初始化完成，日志目录: {self.run_log_dir}")
    
    def _save_config(self):
        """将配置保存到日志目录"""
        config_file = os.path.join(self.run_log_dir, "config.json")
        
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(json.dumps(self.config,indent=2,ensure_ascii=False))
        
        logging.info(f"配置已保存到: {config_file}")
    
    def get_log_dir(self) -> str:
        """获取当前运行的日志目录"""
        return self.run_log_dir
    
    def get_timestamp(self) -> str:
        """获取当前运行的时间戳"""
        return self.timestamp
