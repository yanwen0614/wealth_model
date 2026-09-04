import numpy as np
import torch
import torch.nn as nn
import logging




class EarlyStopping:
    """
    早停机制类
    职责：监控验证损失，在性能不再提升时提前停止训练
    
    参数:
        patience: 容忍的epoch数量
        verbose: 是否打印详细信息
        delta: 最小改善阈值
        path: 模型保存路径
    """
    def __init__(self, patience: int = 10, verbose: bool = False, 
                 delta: float = 0, path: str = 'best_model.pth'):
        self.patience = patience
        self.verbose = verbose
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.val_loss_min = np.inf
        self.delta = delta
        self.path = path

    def __call__(self, val_loss: float, model: nn.Module):
        """
        检查是否需要早停
        
        参数:
            val_loss: 当前验证损失
            model: 待保存的模型
        """
        score = -val_loss
        if self.best_score is None:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
        elif score < self.best_score + self.delta:
            self.counter += 1
            if self.verbose:
                logger = logging.getLogger(__name__)
                logger.info(f'EarlyStopping counter: {self.counter} out of {self.patience}')


            if self.counter >= self.patience:
                self.early_stop = True
        else:
            self.best_score = score
            self.save_checkpoint(val_loss, model)
            self.counter = 0

    def save_checkpoint(self, val_loss: float, model: nn.Module):
        """
        保存模型检查点
        
        参数:
            val_loss: 当前验证损失
            model: 待保存的模型
        """
        if self.verbose:
            logger = logging.getLogger(__name__)
            logger.info(f'Validation loss decreased ({self.val_loss_min:.6f} --> {val_loss:.6f}). Saving model...')
        torch.save(model.state_dict(), self.path)
        self.val_loss_min = val_loss


