import torch
import logging
import os
import argparse
from data.npz_data_load2 import NPZSequentialDataset2
from data.npz_data_load import DataConfig
from models.model2.model2 import CNNTransformer
from models.model2.config import ModelConfig
from training import Trainer
from visualization import Visualizer
from log_manager import LoggerManager
from training.custom_loss import HalfClassWeightedCrossEntropy


# 全局配置
config = {
    'DEVICE': 'cuda' if torch.cuda.is_available() else 'cpu',
    'NPZ_DIR': './processed_data_train',
    'VAL_NPZ_DIR': './processed_data_val',
    'CACHE_BLOCK_SIZE': 5,
    'BATCH_SIZE': 20480,
    'NUM_WORKERS': 4,
    'INPUT_DIM': 8,
    'SEQ_LEN': 60,
    'NUM_CLASSES': 9,
    'CNN_OUT_CHANNELS': 64,
    'D_MODEL': 128,
    'NHEAD': 8,
    'NUM_ENCODER_LAYERS': 3,
    'DROPOUT_RATE': 0.2,
    'LEARNING_RATE': 1e-3,
    'WEIGHT_DECAY': 1e-5,
    'LARGE_PENALTY': 1.50,
    'EPOCHS': 50,
    'PATIENCE': 10,
    'LOG_DIR': './logs'
}


def main():
    """主程序入口函数"""
    # 1. 解析命令行参数
    parser = argparse.ArgumentParser(description='训练CNNTransformer模型')
    args = parser.parse_args()
    
    # 2. 初始化日志系统
    logger_manager = LoggerManager(config=config)
    logger = logging.getLogger(__name__)
    logger.info("=== 训练开始 ===")
    config["run_log_dir"] = logger_manager.run_log_dir
    # 3. 数据集管理
    logger.info("=== 初始化数据集 ===")
    
    # 创建数据配置
    data_config = DataConfig(
        npz_dir=config['NPZ_DIR'],
        cache_block_size=config['CACHE_BLOCK_SIZE'],
        batch_size=config['BATCH_SIZE'],
        num_workers=config['NUM_WORKERS'],
    )
    
    # 创建训练数据集
    train_loader = NPZSequentialDataset2.create_sequential_dataloader(data_config)
    logger.info(f"训练数据集总样本数: {len(train_loader.dataset)}")
    
    # 如果有验证集
    val_loader = None
    if config['VAL_NPZ_DIR'] and os.path.exists(config['VAL_NPZ_DIR']):
        val_data_config = DataConfig(
            npz_dir=config['VAL_NPZ_DIR'],
            cache_block_size=config['CACHE_BLOCK_SIZE'],
            batch_size=config['BATCH_SIZE'],
            num_workers=config['NUM_WORKERS'],
        )
        val_loader = NPZSequentialDataset2.create_sequential_dataloader(val_data_config)
        logger.info(f"验证数据集总样本数: {len(val_loader.dataset)}")
    
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
    
    # 打印模型基本信息
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"总参数量: {total_params:,}")
    logger.info(f"可训练参数量: {trainable_params:,}")
    logger.info(f"可训练参数比例: {100 * trainable_params / total_params:.2f}%")
    
    # 5. 损失函数和优化器
    logger.info("=== 初始化损失函数和优化器 ===")
    
    # 创建自定义损失函数（不使用类别权重）
    criterion = HalfClassWeightedCrossEntropy(
        num_classes=config['NUM_CLASSES'],
        large_penalty=config['LARGE_PENALTY'],
        class_weights=None,
        reduction='mean'
    )
    
    # 创建优化器
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config['LEARNING_RATE'],
        weight_decay=config['WEIGHT_DECAY']
    )
    
    # 创建学习率调度器
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode='min',
        factor=0.5,
        patience=5,
        verbose=True
    )
    
    # 6. 训练
    logger.info("=== 开始训练 ===")
    
    trainer = Trainer(
        model=model,
        config=config,
        train_loader=train_loader,
        val_loader=val_loader,
        criterion=criterion,
        optimizer=optimizer,
        scheduler=scheduler
    )
    
    trainer.train()
    
    # 7. 可视化
    train_losses, val_losses, train_accs, val_accs = trainer.get_training_history()
    

    
    visualization_path = os.path.join(config["run_log_dir"], "training_curve.png")
    Visualizer.plot_training_curves(train_losses, val_losses, train_accs, val_accs, save_path=visualization_path)
    logger.info(f"训练曲线已保存到: {visualization_path}")
    
    # 8. 加载最佳模型
    model_path = os.path.join(config["run_log_dir"], "best_model.pth")
    model.load_state_dict(torch.load(model_path))
    logger.info(f"加载最佳模型完成: {model_path}")
    
    # 9. 训练结束
    logger.info("=== 训练结束 ===")


if __name__ == "__main__":
    main()
