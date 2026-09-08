import logging
import os
from typing import List, Optional, Tuple

import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import confusion_matrix
from tqdm import tqdm

from .batch import _compute_loss, _unpack_batch, _unpack_outputs
from .early_stopping import EarlyStopping
from .metrics import calculate_latter_half_metrics
from .reporting import save_confusion_matrix

class Trainer:
    """
    训练器类
    职责：封装完整的训练和验证流程
    
    参数:
        model: 待训练的模型
        config: 配置字典
        train_loader: 训练数据加载器
        val_loader: 验证数据加载器
        criterion: 损失函数（可选）
        optimizer: 优化器（可选）
        scheduler: 学习率调度器（可选）
    """
    def __init__(self, model: nn.Module, config: dict,
                 train_loader: torch.utils.data.DataLoader, val_loader: torch.utils.data.DataLoader = None,
                 criterion: nn.Module = None, optimizer: optim.Optimizer = None, scheduler: optim.lr_scheduler._LRScheduler = None):
        self.model = model
        self.config = config
        self.train_loader = train_loader
        self.val_loader = val_loader
        
        # 初始化训练组件
        self.criterion = criterion
        
        # 初始化优化器
        self.optimizer = optimizer
        
        # 初始化学习率调度器
        self.scheduler = scheduler

        
        # 获取日志目录（如果存在）
        os.makedirs(config["run_log_dir"], exist_ok=True)
        
        # 早停机制，模型保存到日志目录
        self.early_stopping = EarlyStopping(
            patience=config.get('PATIENCE', 10), 
            verbose=True,
            path=os.path.join(config["run_log_dir"], "best_model.pth")
        )
        
        # 训练历史记录
        self.train_losses = []
        self.val_losses = []
        self.train_accs = []
        self.val_accs = []
        
        # 设备配置
        self.device = config.get('DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        self.criterion.to(self.device)
        
        # 日志记录器
        self.logger = logging.getLogger(__name__)
        
        # 全局步数计数器
        self.global_step = 0
        
    def train_epoch(self, epoch: int) -> Tuple[float, float]:
        """
        训练一个epoch
        
        参数:
            epoch: 当前epoch编号
        
        返回:
            avg_train_loss: 平均训练损失
            avg_train_acc: 平均训练准确率
        """
        self.model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0
        
        for batch_idx, batch in tqdm(enumerate(self.train_loader),desc="batch train",total=len(self.train_loader)):
            data, labels, y_ret = _unpack_batch(batch)
            data, labels = data.to(self.device), labels.to(self.device)
            y_ret = y_ret.to(self.device) if y_ret is not None else None

            self.optimizer.zero_grad()
            logits, ret_pred = _unpack_outputs(self.model(data))  # 单/双头兼容
            loss = _compute_loss(self.criterion, logits, ret_pred, labels, y_ret)
            loss.backward()
            self.optimizer.step()

            # 更新全局步数
            self.global_step += 1

            train_loss += loss.item() * data.size(0)
            _, preds = torch.max(logits, 1)
            train_correct += (preds == labels).sum().item()
            train_total += labels.size(0)
            
            if (batch_idx + 1) % 100 == 0:
                self.logger.info(f'Epoch [{epoch+1}/{self.config.get("EPOCHS", 50)}], Batch [{batch_idx+1}/{len(self.train_loader)}], Loss: {loss.item():.4f}')
        
        avg_train_loss = train_loss / train_total
        avg_train_acc = train_correct / train_total
        return avg_train_loss, avg_train_acc
    
    def validate_epoch(self) -> Tuple[float, float, torch.Tensor, torch.Tensor]:
        """
        验证一个epoch
        
        返回:
            avg_val_loss: 平均验证损失
            avg_val_acc: 平均验证准确率
            all_labels: 所有真实标签
            all_preds: 所有预测标签
        """
        self.model.eval()
        val_loss = 0.0 
        val_correct = 0
        val_total = 0
        all_labels = []
        all_preds = []
        
        with torch.no_grad():
            for batch in self.val_loader:
                data, labels, y_ret = _unpack_batch(batch)
                data, labels = data.to(self.device), labels.to(self.device)
                y_ret = y_ret.to(self.device) if y_ret is not None else None
                logits, ret_pred = _unpack_outputs(self.model(data))  # 单/双头兼容
                loss = _compute_loss(self.criterion, logits, ret_pred, labels, y_ret)

                val_loss += loss.item() * data.size(0)
                _, preds = torch.max(logits, 1)
                val_correct += (preds == labels).sum().item()
                val_total += labels.size(0)
                
                all_labels.append(labels.cpu())
                all_preds.append(preds.cpu())
        
        avg_val_loss = val_loss / val_total
        avg_val_acc = val_correct / val_total
        all_labels = torch.cat(all_labels)
        all_preds = torch.cat(all_preds)
        
        return avg_val_loss, avg_val_acc, all_labels, all_preds
    
    def print_confusion_matrix(self, labels: torch.Tensor, preds: torch.Tensor, epoch: Optional[int] = None):
        """打印并保存混淆矩阵。"""
        num_classes = self.config.get('num_classes')
        class_names = [str(i) for i in range(num_classes)]
        cm = confusion_matrix(labels.numpy(), preds.numpy(), labels=range(num_classes))
        
        self.logger.info("=" * 50)
        self.logger.info("                混淆矩阵（文本版）")
        self.logger.info("=" * 50)
        
        header = "真实标签\\预测标签" + "".join([f"{name:>8}" for name in class_names])
        self.logger.info(header)
        for i, row in enumerate(cm):
            row_str = f"{class_names[i]:>16}" + "".join([f"{val:>8}" for val in row])
            self.logger.info(row_str)
        self.save_confusion_matrix(cm, class_names, epoch)

    def save_confusion_matrix(self, cm, class_names, epoch: Optional[int] = None):
        """保留旧接口，实际输出由 reporting 模块完成。"""
        save_confusion_matrix(cm, class_names, self.config.get('run_log_dir', './logs'), epoch, self.logger)
    
    def train(self):
        """执行完整的训练流程"""
        # 检查验证集是否存在
        has_val = self.val_loader is not None
        if len(self.train_loader.dataset) == 0:
            raise ValueError("训练集为空，无法开始训练")
        if has_val and len(self.val_loader.dataset) == 0:
            raise ValueError("验证集为空，无法执行验证")
        
        # 打印训练基本信息
        train_size = len(self.train_loader.dataset)
        val_size = len(self.val_loader.dataset) if has_val else 0
        self.logger.info(f"开始训练（总样本数: {train_size + val_size}, "
              f"训练集: {train_size}, 验证集: {val_size}）")
        
        # 初始化最佳验证结果
        best_val_loss = float('inf')
        best_val_acc = 0.0
        
        epochs = self.config.get('EPOCHS', 50)
        for epoch in tqdm(range(epochs),desc="epochs train"):
            # 训练阶段
            avg_train_loss, avg_train_acc = self.train_epoch(epoch)
            self.train_losses.append(avg_train_loss)
            self.train_accs.append(avg_train_acc)
            
            # 打印当前学习率
            current_lr = self.optimizer.param_groups[0]['lr']
            self.logger.info(f"Epoch [{epoch+1}/{epochs}], 当前学习率: {current_lr:.6f}")
            
            # 验证阶段
            if has_val:
                avg_val_loss, avg_val_acc, all_labels, all_preds = self.validate_epoch()
                self.val_losses.append(avg_val_loss)
                self.val_accs.append(avg_val_acc)
                
                # 更新最佳验证结果
                if avg_val_loss < best_val_loss:
                    best_val_loss = avg_val_loss
                if avg_val_acc > best_val_acc:
                    best_val_acc = avg_val_acc
                
                if (epoch + 1) % 1 == 0:
                    self.print_confusion_matrix(all_labels, all_preds, epoch)
                
                # 计算并打印涨跌二分类指标
                try:
                    precision, recall = calculate_latter_half_metrics(
                        all_labels, all_preds, num_classes=self.config.get('num_classes')
                    )
                    self.logger.info(f'涨跌二分类 - 涨类精确率: {precision:.4f}, 涨类召回率: {recall:.4f}')
                except Exception as e:
                    self.logger.warning(f'计算后半类指标失败: {e}')
                
                # 打印epoch结果（包含最佳验证结果）
                self.logger.info(f'Epoch [{epoch+1}/{epochs}], '
                      f'Train Loss: {avg_train_loss:.4f}, Train Acc: {avg_train_acc:.4f}, '
                      f'Val Loss: {avg_val_loss:.4f}, Val Acc: {avg_val_acc:.4f}, '
                      f'Best Val Loss: {best_val_loss:.4f}, Best Val Acc: {best_val_acc:.4f}')
                
                # 早停检查
                self.early_stopping(avg_val_loss, self.model)
                if self.early_stopping.early_stop:
                    self.logger.info("早停触发，停止训练")
                    break
                
                # 更新学习率
                self.update_scheduler_epoch()

            
        # 训练结束，加载最佳模型
        if has_val:
            self.model.load_state_dict(torch.load(self.early_stopping.path, map_location=self.device))
            self.logger.info(f"训练结束，已加载最佳模型: {self.early_stopping.path}")
        else:
            self.logger.info("训练结束（无验证集，未保存模型）")
    

    def update_scheduler_epoch(self):
        if self.scheduler is not None:
            if isinstance(self.scheduler, optim.lr_scheduler.ReduceLROnPlateau):
                self.scheduler.step(self.val_losses[-1])
            else:
                self.scheduler.step()
            
            # 打印学习率变化
            if hasattr(self.scheduler, 'get_last_lr'):
                self.logger.info(f"当前学习率：{self.scheduler.get_last_lr()}")
    
    def update_scheduler_step(self):
        if self.scheduler is not None :
            if isinstance(self.scheduler, optim.lr_scheduler.ReduceLROnPlateau):
                pass
            else:
                self.scheduler.step()
            # 打印学习率变化
            if hasattr(self.scheduler, 'get_last_lr'):
                self.logger.info(f"当前学习率：{self.scheduler.get_last_lr()}")

    def get_training_history(self) -> Tuple[List[float], List[float], List[float], List[float]]:
        """
        获取训练历史记录
        
        返回:
            train_losses: 训练损失列表
            val_losses: 验证损失列表
            train_accs: 训练准确率列表
            val_accs: 验证准确率列表
        """
        return self.train_losses, self.val_losses, self.train_accs, self.val_accs
