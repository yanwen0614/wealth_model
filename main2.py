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
from criterion.EMD_loss import EMDLoss
import numpy as np

# 全局配置
config = {
    
    'DEVICE': 'cuda' if torch.cuda.is_available() else 'cpu',

    # data 
    'NPZ_DIR': './processed_data_train',
    'VAL_NPZ_DIR': './processed_data_val',
    "BINS": (np.linspace(-25,25,51)/ 100).tolist(),
    'CACHE_BLOCK_SIZE': 3,
    'BATCH_SIZE': 256,
    'NUM_WORKERS': 2,

    # model
    "model":"CNNTransformer",
    "CNNTransformerConfig":{
        'featurenum': 8,
        'seq_len': 60,
        'num_classes': 62,
        'cnn_out_channels': 128,
        'd_model': 256,
        'nhead': 8,
        "cnn_kernel_sizes":[1,3,5,7,10],
        'num_encoder_layers': 6,
        'dropout_rate': 0.3,
    },

    # criterion
    "criterion":"EMLoss",
    "EMLossConfig":dict(
        p = 2,
        label_smoothing=True, 
        smooth_eps=0.1),

    # lr scheduler
    "scheduler":"ReduceLROnPlateau",
    'LEARNING_RATE': 1e-4,    # 初始学习率（预热开始时的学习率）
    'WEIGHT_DECAY': 1e-5,
    'EPOCHS': 100,
    'PATIENCE': 20,

    # log
    'LOG_DIR': './logs',
}

config['num_classes'] = len(config['BINS'])+1
config["CNNTransformerConfig"]['num_classes'] = len(config['BINS'])+1

print(config)


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

    
    # 4. 模型初始化
    logger.info("=== 初始化模型 ===")
    
    # 创建模型配置

    
    # 创建模型
    model = CNNTransformer(ModelConfig(**config["CNNTransformerConfig"])).to(config['DEVICE'])
    
    # 打印模型基本信息
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"总参数量: {total_params:,}")
    logger.info(f"可训练参数量: {trainable_params:,}")
    logger.info(f"可训练参数比例: {100 * trainable_params / total_params:.2f}%")
    
    # 5. 损失函数和优化器
    logger.info("=== 初始化损失函数和优化器 ===")
    
    criterion = EMDLoss(num_classes=config['num_classes'], **config['EMLossConfig'])
    
    # 创建优化器
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config['LEARNING_RATE'],
        weight_decay=config['WEIGHT_DECAY']
    )

    # 创建学习率调度器
    if config['scheduler'] == "ReduceLROnPlateau":
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode='min',
            factor=0.5,
            patience=config['PATIENCE'],
            verbose=True
        )
    elif config['scheduler'] == "CosineAnnealingWarmRestarts":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
            optimizer, T_0=10, T_mult=2, eta_min=1e-6
        )
    else:
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer,
            mode='min',
            factor=0.5,
            patience=config['PATIENCE'],
            verbose=True
        )

    
    # 3. 数据集管理
    logger.info("=== 初始化数据集 ===")
    
    # 创建数据配置
    data_config = DataConfig(
        npz_dir=config['NPZ_DIR'],
        cache_block_size=config['CACHE_BLOCK_SIZE'],
        batch_size=config['BATCH_SIZE'],
        num_workers=config['NUM_WORKERS'],
        bins=config['BINS']
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
            bins=config['BINS']
        )
        val_loader = NPZSequentialDataset2.create_sequential_dataloader(val_data_config)
        logger.info(f"验证数据集总样本数: {len(val_loader.dataset)}")

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
    try:
        trainer.train()
    except KeyboardInterrupt as e:
        pass
    
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
