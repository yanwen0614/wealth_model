import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import logging
from typing import List




class Visualizer:
    """
    可视化类
    职责：负责训练结果的可视化展示
    """
    @staticmethod
    def plot_training_curves(train_losses: List[float], val_losses: List[float],
                            train_accs: List[float], val_accs: List[float],
                            save_path: str = 'training_curve.png'):
        """
        绘制训练曲线
        
        参数:
            train_losses: 训练损失列表
            val_losses: 验证损失列表
            train_accs: 训练准确率列表
            val_accs: 验证准确率列表
            save_path: 图片保存路径
        """
        plt.figure(figsize=(12, 4))
        
        # 损失曲线
        plt.subplot(1, 2, 1)
        plt.plot(train_losses, label='Train Loss')
        plt.plot(val_losses, label='Val Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.legend()
        plt.title('Loss Curve')
        
        # 准确率曲线
        plt.subplot(1, 2, 2)
        plt.plot(train_accs, label='Train Acc')
        plt.plot(val_accs, label='Val Acc')
        plt.xlabel('Epoch')
        plt.ylabel('Accuracy')
        plt.legend()
        plt.title('Accuracy Curve')
        
        plt.savefig(save_path)
        plt.close()
        logger = logging.getLogger(__name__)
        logger.info(f"训练曲线已保存至: {save_path}")


