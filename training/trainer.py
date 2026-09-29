import csv
import logging
import os
from typing import Any, cast

import numpy as np
import torch
from sklearn.metrics import confusion_matrix
from torch import nn, optim
from tqdm import tqdm

from .batch import _compute_loss, _unpack_batch, _unpack_outputs
from .checkpoint import load_model_state
from .early_stopping import EarlyStopping
from .metrics import calculate_latter_half_metrics
from .reporting import save_confusion_matrix


class ValidationResult(dict):
    """validate_epoch 统一返回：dict 访问 + 旧 tuple 解包兼容。

    新代码走 ``res["loss"]`` / ``res["precision"]``（零售）；
    旧调用 ``loss, acc, labels, preds = validate_epoch()`` 经 __iter__ 仍可用。
    """

    def __init__(self, loss: float, accuracy: float,
                 labels: torch.Tensor, preds: torch.Tensor, **extra):
        super().__init__(loss=loss, accuracy=accuracy, labels=labels, preds=preds, **extra)

    def __iter__(self):
        yield self["loss"]
        yield self["accuracy"]
        yield self["labels"]
        yield self["preds"]


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
                 train_loader: torch.utils.data.DataLoader, val_loader: torch.utils.data.DataLoader | None = None,
                 criterion: nn.Module | None = None, optimizer: optim.Optimizer | None = None, scheduler: optim.lr_scheduler._LRScheduler | None = None):
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
        assert self.criterion is not None, "Trainer 需要 criterion（损失函数）"
        self.criterion.to(self.device)
        
        # 日志记录器
        self.logger = logging.getLogger(__name__)
        
        # 全局步数计数器
        self.global_step = 0

        # ── 零售模式 ──
        self._is_retail = config.get("MODEL") == "retail_friendly"
        if self._is_retail:
            self.val_precisions: list[float] = []
            self.val_recalls: list[float] = []
            self.val_f1s: list[float] = []
            self.val_avg_p_bin: list[float] = []
            self.calibrated_threshold: float = config.get("RETAIL_DEFAULT_THRESHOLD", 0.5)
            self.calibration_report: dict = {}
            self._metrics_csv_path = os.path.join(config["run_log_dir"], "epoch_metrics.csv")
            self._init_metrics_csv()

    # ── 标签二值化（零售；原 RetailTrainer.binarize_labels）──

    @staticmethod
    def binarize_labels(
        y_cls: torch.Tensor,
        y_ret: torch.Tensor | None = None,
        half: int = 26,
    ) -> torch.Tensor:
        """52 类标签转二分类：优先 y_ret > 0，回退 y_cls >= half。"""
        if y_ret is not None:
            return (y_ret > 0.0).float()
        return (y_cls >= half).float()

    # ── CSV 指标追踪（零售；原 RetailTrainer._init/_append_epoch_metrics）──

    def _init_metrics_csv(self):
        """初始化 epoch 指标 CSV（写入表头；失败只告警）。"""
        os.makedirs(os.path.dirname(self._metrics_csv_path), exist_ok=True)
        try:
            with open(self._metrics_csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    "epoch", "train_loss", "val_loss", "val_precision",
                    "val_recall", "val_f1", "val_avg_p_bin", "lr"
                ])
            self.logger.info(f"指标 CSV 已创建: {self._metrics_csv_path}")
        except OSError as e:
            self.logger.warning(f"无法创建指标 CSV: {e}")

    def _append_epoch_metrics(
        self, epoch: int, train_loss: float,
        val_metrics: dict | None = None
    ):
        """追加当前 epoch 指标到 CSV。"""
        current_lr = self.optimizer.param_groups[0]["lr"] if self.optimizer else 0.0
        try:
            with open(self._metrics_csv_path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    epoch + 1,
                    f"{train_loss:.6f}",
                    f"{val_metrics['loss']:.6f}" if val_metrics else "",
                    f"{val_metrics['precision']:.6f}" if val_metrics else "",
                    f"{val_metrics['recall']:.6f}" if val_metrics else "",
                    f"{val_metrics['f1']:.6f}" if val_metrics else "",
                    f"{val_metrics['avg_p_bin']:.6f}" if val_metrics else "",
                    f"{current_lr:.8f}",
                ])
        except OSError as e:
            self.logger.warning(f"无法写入指标 CSV: {e}")
        
    def train_epoch(self, epoch: int) -> tuple[float, float]:
        """
        训练一个epoch
        
        参数:
            epoch: 当前epoch编号
        
        返回:
            avg_train_loss: 平均训练损失
            avg_train_acc: 平均训练准确率
        """
        assert self.optimizer is not None, "训练需要 optimizer"
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
            if self._is_retail:
                p_bin = torch.sigmoid(logits)
                preds_bin = (p_bin > 0.5).long()
                y_bin = self.binarize_labels(labels, y_ret)
                train_correct += (preds_bin == y_bin.long()).sum().item()
            else:
                _, preds = torch.max(logits, 1)
                train_correct += (preds == labels).sum().item()
            train_total += labels.size(0)
            
            if (batch_idx + 1) % 100 == 0:
                self.logger.info(f'Epoch [{epoch+1}/{self.config.get("EPOCHS", 50)}], Batch [{batch_idx+1}/{len(self.train_loader)}], Loss: {loss.item():.4f}')
        
        avg_train_loss = train_loss / train_total
        avg_train_acc = train_correct / train_total
        return avg_train_loss, avg_train_acc
    
    def validate_epoch(self) -> ValidationResult:
        """
        验证一个epoch（普通模式：52类；零售模式：二分类+precision/recall/F1）

        返回 ValidationResult（dict）：``loss/accuracy/labels/preds`` 通用键，
        零售模式追加 ``precision/recall/f1/avg_p_bin/pos_ratio/n_val``；
        支持旧式 ``loss, acc, labels, preds = validate_epoch()`` 解包。
        """
        assert self.val_loader is not None, "验证需要 val_loader"
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
                if self._is_retail:
                    p_bin = torch.sigmoid(logits)
                    preds_bin = (p_bin >= self.calibrated_threshold).long()
                    y_bin = self.binarize_labels(labels, y_ret)
                    val_correct += (preds_bin == y_bin.long()).sum().item()
                    all_labels.append(y_bin.cpu())
                    all_preds.append(p_bin.cpu())  # 存概率用于校准
                else:
                    _, preds = torch.max(logits, 1)
                    val_correct += (preds == labels).sum().item()
                    all_labels.append(labels.cpu())
                    all_preds.append(preds.cpu())
                val_total += labels.size(0)
        
        avg_val_loss = val_loss / val_total
        avg_val_acc = val_correct / val_total
        all_labels = torch.cat(all_labels)
        all_preds = torch.cat(all_preds)

        if self._is_retail:
            # 零售模式：计算 precision/recall/F1
            y_bin_all = all_labels  # [N]
            p_bin_all = all_preds   # [N] (概率)
            preds_at_th = (p_bin_all >= self.calibrated_threshold).float()
            tp = ((preds_at_th == 1) & (y_bin_all == 1)).sum().item()
            fp = ((preds_at_th == 1) & (y_bin_all == 0)).sum().item()
            fn = ((preds_at_th == 0) & (y_bin_all == 1)).sum().item()
            prec = tp / max(tp + fp, 1)
            rec = tp / max(tp + fn, 1)
            f1 = 2 * prec * rec / max(prec + rec, 1e-8)
            self.val_precisions.append(prec)
            self.val_recalls.append(rec)
            self.val_f1s.append(f1)
            self.val_avg_p_bin.append(float(p_bin_all.mean()))
            self.logger.info(
                f'  Val Precision: {prec:.2%}  Recall: {rec:.2%}  '
                f'F1: {f1:.3f}  p_bin avg: {float(p_bin_all.mean()):.3f}'
            )
            return ValidationResult(
                avg_val_loss, avg_val_acc, all_labels, all_preds,
                precision=prec, recall=rec, f1=f1,
                avg_p_bin=float(p_bin_all.mean()),
                pos_ratio=float(y_bin_all.float().mean()),
                n_val=val_total,
            )

        return ValidationResult(avg_val_loss, avg_val_acc, all_labels, all_preds)
    
    def print_confusion_matrix(self, labels: torch.Tensor, preds: torch.Tensor, epoch: int | None = None):
        """打印并保存混淆矩阵。"""
        num_classes = self.config.get('num_classes')
        assert isinstance(num_classes, int), "config 缺少 num_classes(int)"
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

    def save_confusion_matrix(self, cm, class_names, epoch: int | None = None):
        """保留旧接口，实际输出由 reporting 模块完成。"""
        save_confusion_matrix(cm, class_names, self.config.get('run_log_dir', './logs'), epoch, self.logger)

    # ── 零售模式：阈值校准 ──

    @torch.no_grad()
    def calibrate_threshold(
        self,
        target_precision: float = 0.75,
        min_threshold: float = 0.50,
        max_threshold: float = 0.95,
        step: float = 0.025,
    ) -> float:
        """校准决策阈值，使验证集 precision 达到目标值。

        验证集预测已由最后一次 validate_epoch 收集在 val_preds 中。
        """
        self.logger.info("=" * 52)
        self.logger.info(f"阈值校准: 目标 precision ≥ {target_precision:.0%}")
        self.logger.info("-" * 52)

        # --- 这里简化实现：重新跑一次 val 收集 p_bin ---
        # 在零售模式下，validate_epoch 已经存了概率在 all_preds，但 train() 中
        # 最后一次 validate_epoch 的数据还在内存。更稳妥：重新收集
        all_p_bin: list[torch.Tensor] = []
        all_y_bin: list[torch.Tensor] = []
        all_y_ret: list[torch.Tensor] = []

        self.model.eval()
        for batch in self.val_loader:
            data, labels, y_ret = _unpack_batch(batch)
            data = data.to(self.device)
            y_bin = self.binarize_labels(labels, y_ret)
            logits, _ = _unpack_outputs(self.model(data))
            p_bin = torch.sigmoid(logits)
            all_p_bin.append(p_bin.cpu())
            all_y_bin.append(y_bin.cpu())
            if y_ret is not None:
                all_y_ret.append(y_ret.cpu())

        p_bin_all = torch.cat(all_p_bin).numpy()
        y_bin_all = torch.cat(all_y_bin).numpy()
        y_ret_all = torch.cat(all_y_ret).numpy() if all_y_ret else None

        thresholds = np.arange(min_threshold, max_threshold + step, step)
        results: list = []

        for th in thresholds:
            preds = (p_bin_all >= th).astype(np.float32)
            tp = ((preds == 1) & (y_bin_all == 1)).sum()
            fp = ((preds == 1) & (y_bin_all == 0)).sum()
            fn = ((preds == 0) & (y_bin_all == 1)).sum()
            n_pos = int(preds.sum())
            prec = tp / max(tp + fp, 1)
            rec = tp / max(tp + fn, 1)
            f1 = 2 * prec * rec / max(prec + rec, 1e-8)
            avg_ret = float(y_ret_all[preds == 1].mean()) if n_pos > 0 and y_ret_all is not None else float("nan")
            results.append((th, prec, rec, f1, n_pos, avg_ret))

        # 打印校准报告
        self.logger.info(f"{'阈值':>6} | {'精确率':>8} | {'召回率':>8} | {'F1':>6} | {'选股数':>8} | {'均涨幅':>8}")
        self.logger.info("-" * 60)
        for th, prec, rec, f1, n, avg_ret in results:
            if prec >= target_precision - 0.05 or n > 0:
                avg_ret_str = f"{avg_ret:>8.4f}" if np.isfinite(avg_ret) else "     nan"
                self.logger.info(f"{th:>6.3f} | {prec:>8.2%} | {rec:>8.2%} | {f1:>6.3f} | {n:>8d} | {avg_ret_str}")

        # 选最佳：满足 precision >= target 的最低阈值
        valid = [r for r in results if r[1] >= target_precision and r[4] > 0]
        if valid:
            best_th, best_prec, best_rec, best_f1, best_n, best_avg_r = valid[0]
        else:
            best_idx = int(np.argmax([r[1] for r in results]))
            best_th, best_prec, best_rec, best_f1, best_n, best_avg_r = results[best_idx]
            self.logger.warning(f"⚠ 无法达 target_precision={target_precision:.0%}，取最高 precision")

        self.calibrated_threshold = float(best_th)
        self.calibration_report = {
            "threshold": float(best_th),
            "precision": float(best_prec),
            "recall": float(best_rec),
            "f1": float(best_f1),
            "n_picks": int(best_n),
            "avg_ret_when_pick": float(best_avg_r) if np.isfinite(best_avg_r) else None,
            "target_precision": target_precision,
        }

        self.logger.info("-" * 60)
        avg_ret_str = f"{best_avg_r:.4f}" if np.isfinite(best_avg_r) else "nan"
        self.logger.info(f"✓ 选定阈值={best_th:.3f}  |  precision={best_prec:.2%}  recall={best_rec:.2%}  选股数={best_n}  均涨幅={avg_ret_str}")
        self.logger.info("=" * 52)
        return float(best_th)
    
    def train(self):
        """执行完整的训练流程"""
        # 检查验证集是否存在
        val_loader = self.val_loader
        has_val = val_loader is not None
        if len(cast(Any, self.train_loader.dataset)) == 0:
            raise ValueError("训练集为空，无法开始训练")
        if val_loader is not None and len(cast(Any, val_loader.dataset)) == 0:
            raise ValueError("验证集为空，无法执行验证")

        # 打印训练基本信息
        train_size = len(cast(Any, self.train_loader.dataset))
        val_size = len(cast(Any, val_loader.dataset)) if val_loader is not None else 0
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
            assert self.optimizer is not None, "训练需要 optimizer"
            current_lr = self.optimizer.param_groups[0]['lr']
            self.logger.info(f"Epoch [{epoch+1}/{epochs}], 当前学习率: {current_lr:.6f}")
            
            # 验证阶段（dict 访问；ValidationResult 仍兼容旧 tuple 解包）
            if has_val:
                val_res = self.validate_epoch()
                avg_val_loss = val_res["loss"]
                avg_val_acc = val_res["accuracy"]
                all_labels = val_res["labels"]
                all_preds = val_res["preds"]
                self.val_losses.append(avg_val_loss)
                self.val_accs.append(avg_val_acc)

                if self._is_retail:
                    self._append_epoch_metrics(epoch, avg_train_loss, val_res)
                
                # 更新最佳验证结果
                best_val_loss = min(best_val_loss, avg_val_loss)
                best_val_acc = max(best_val_acc, avg_val_acc)
                
                if not self._is_retail:
                    # 普通模式：混淆矩阵 + 涨跌二分类指标
                    if (epoch + 1) % 1 == 0:
                        self.print_confusion_matrix(all_labels, all_preds, epoch)

                    # 计算并打印涨跌二分类指标
                    try:
                        num_classes_metric = self.config.get('num_classes')
                        assert isinstance(num_classes_metric, int), "config 缺少 num_classes(int)"
                        precision, recall = calculate_latter_half_metrics(
                            all_labels, all_preds, num_classes=num_classes_metric
                        )
                        self.logger.info(f'涨跌二分类 - 涨类精确率: {precision:.4f}, 涨类召回率: {recall:.4f}')
                    except Exception as e:  # noqa: BLE001 - 指标计算失败只告警，不中断训练
                        self.logger.warning(f'计算后半类指标失败: {e}')
                
                # 打印epoch结果（包含最佳验证结果）
                self.logger.info(f'Epoch [{epoch+1}/{epochs}], '
                      f'Train Loss: {avg_train_loss:.4f}, Train Acc: {avg_train_acc:.4f}, '
                      f'Val Loss: {avg_val_loss:.4f}, Val Acc: {avg_val_acc:.4f}, '
                      f'Best Val Loss: {best_val_loss:.4f}, Best Val Acc: {best_val_acc:.4f}')
                
                # 早停检查（T14：best ckpt 存 optimizer/scheduler/epoch/config，中断后续训连续）
                self.early_stopping(avg_val_loss, self.model, optimizer=self.optimizer,
                                    scheduler=self.scheduler, epoch=epoch,
                                    config=dict(self.config))
                if self.early_stopping.early_stop:
                    self.logger.info("早停触发，停止训练")
                    break
                
                # 更新学习率
                self.update_scheduler_epoch()

            
        # 训练结束，加载最佳模型（T14：新 dict / 旧裸 state_dict 均兼容）
        if has_val:
            meta = load_model_state(self.early_stopping.path, self.model,
                                    map_location=self.device)
            self.logger.info(f"训练结束，已加载最佳模型: {self.early_stopping.path}"
                             + (f" (epoch={meta['epoch']})" if meta["epoch"] is not None else ""))
            # 零售模式：阈值校准
            if self._is_retail:
                self.logger.info("")
                self.calibrate_threshold(
                    target_precision=self.config.get("RETAIL_TARGET_PRECISION", 0.75),
                )
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

    def get_training_history(self) -> tuple[list[float], list[float], list[float], list[float]] | dict:
        """
        获取训练历史记录
         
        返回:
            普通模式: (train_losses, val_losses, train_accs, val_accs)
            零售模式: dict 含 loss/acc 及 precision/recall/f1/calibration
        """
        if self._is_retail:
            return {
                "train_losses": self.train_losses,
                "val_losses": self.val_losses,
                "val_precisions": self.val_precisions,
                "val_recalls": self.val_recalls,
                "val_f1s": self.val_f1s,
                "val_avg_p_bin": self.val_avg_p_bin,
                "calibrated_threshold": self.calibrated_threshold,
                "calibration_report": self.calibration_report,
            }
        return self.train_losses, self.val_losses, self.train_accs, self.val_accs
