"""散户友好模型训练器：面向高精度（precision ≥ 75%）的训练与阈值校准。

职责：
  1. 将 52 类标签转为二分类标签（y_bin = future_ret > 0）
  2. 使用 RetailLoss（ASL + λ*Huber）训练
  3. 验证时追踪 precision / recall / F1 / avg_p_bin
  4. 训练后自动校准决策阈值，使验证集 precision ≥ 75%
  5. 复用现有 EarlyStopping 做早停

与现有 Trainer 的区别：
  - 标签为二分类（而非 52 类有序分类）
  - 主指标为 precision 而非 accuracy
  - 损失为 RetailLoss（非对称聚焦）而非 EMDLoss

复用：
  - EarlyStopping（training/early_stopping.py）
  - build_optimizer_scheduler（training/factory.py）
  - batch._unpack_batch（training/batch.py）
"""

import csv
import logging
import os
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from tqdm import tqdm

from models.retail_friendly.loss import RetailLoss
from models.retail_friendly.model import RetailFriendlyModel
from training.batch import _unpack_batch
from training.early_stopping import EarlyStopping


class RetailTrainer:
    """散户模型训练器。

    Args:
        model: RetailFriendlyModel 实例
        config: 配置字典（含 run_log_dir, DEVICE, EPOCHS, PATIENCE 等顶层键）
        train_loader: 训练 DataLoader
        val_loader: 验证 DataLoader
        criterion: RetailLoss 实例（或自定义）
        optimizer: 优化器
        scheduler: 学习率调度器
    """

    def __init__(
        self,
        model: RetailFriendlyModel,
        config: dict,
        train_loader: torch.utils.data.DataLoader,
        val_loader: Optional[torch.utils.data.DataLoader] = None,
        criterion: Optional[RetailLoss] = None,
        optimizer: Optional[optim.Optimizer] = None,
        scheduler: Optional[optim.lr_scheduler._LRScheduler] = None,
    ):
        self.model = model
        self.config = config
        self.train_loader = train_loader
        self.val_loader = val_loader

        self.criterion = criterion or RetailLoss(
            gamma_neg=config.get("RETAIL_GAMMA_NEG", 4.0),
            lambda_reg=config.get("RETAIL_LAMBDA_REG", 0.3),
            huber_delta=config.get("HUBER_DELTA", 1.0),
        )
        self.optimizer = optimizer
        self.scheduler = scheduler

        self.device = config.get("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.criterion.to(self.device)

        os.makedirs(config["run_log_dir"], exist_ok=True)
        self.logger = logging.getLogger(__name__)

        # ── 复用现有 EarlyStopping ──
        self.early_stopping = EarlyStopping(
            patience=config.get("PATIENCE", 10),
            verbose=True,
            path=os.path.join(config["run_log_dir"], "best_model.pth"),
        )

        # 训练历史
        self.train_losses: List[float] = []
        self.val_losses: List[float] = []
        self.val_precisions: List[float] = []
        self.val_recalls: List[float] = []
        self.val_f1s: List[float] = []
        self.val_avg_p_bin: List[float] = []

        # 决策阈值校准结果（初始取默认值，训练后校准）
        self.calibrated_threshold: float = config.get("RETAIL_DEFAULT_THRESHOLD", 0.65)
        self.calibration_report: dict = {}

        # ── CSV 指标追踪 ──
        self._metrics_csv_path = os.path.join(config["run_log_dir"], "epoch_metrics.csv")
        self._init_metrics_csv()

    # ── 标签二值化 ──

    @staticmethod
    def binarize_labels(
        y_cls: torch.Tensor,
        y_ret: Optional[torch.Tensor] = None,
        half: int = 26,
    ) -> torch.Tensor:
        """将 52 类标签转为二分类标签。

        优先使用 y_ret（future_ret > 0），
        回退使用 y_cls >= half（类索引 26-51 对应正收益）。
        """
        if y_ret is not None:
            return (y_ret > 0.0).float()
        return (y_cls >= half).float()

    # ── CSV 指标追踪 ──

    def _init_metrics_csv(self):
        """初始化 epoch 指标 CSV 文件（写入表头）。"""
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
        val_metrics: Optional[dict] = None
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

    # ── 训练一轮 ──

    def train_epoch(self, epoch: int) -> float:
        """训练一个 epoch。

        Returns:
            平均训练损失
        """
        self.model.train()
        total_loss = 0.0
        n_samples = 0

        pbar = tqdm(
            self.train_loader,
            desc=f"Train E{epoch + 1}",
            total=len(self.train_loader),
        )
        for batch in pbar:
            data, y_cls, y_ret = _unpack_batch(batch)
            data = data.to(self.device)
            y_bin = self.binarize_labels(y_cls, y_ret).to(self.device)
            if y_ret is not None:
                y_ret = y_ret.to(self.device)

            self.optimizer.zero_grad()

            # 前向
            p_bin, ret_pred = self.model(data)

            # 损失（复用 RetailLoss）
            loss = self.criterion(p_bin, ret_pred, y_bin, y_ret)
            loss.backward()
            self.optimizer.step()

            bs = data.size(0)
            total_loss += loss.item() * bs
            n_samples += bs

            pbar.set_postfix({"loss": f"{loss.item():.4f}"})

        avg_loss = total_loss / max(n_samples, 1)
        self.train_losses.append(avg_loss)
        return avg_loss

    # ── 验证一轮 ──

    @torch.no_grad()
    def validate_epoch(self) -> dict:
        """验证一个 epoch，计算当前阈值下二分类指标。

        Returns:
            metrics 字典包含：
              - loss: 平均验证损失
              - precision: 精确率
              - recall: 召回率
              - f1: F1 分数
              - avg_p_bin: 平均预测概率
              - pos_ratio: 验证集正类占比
              - n_val: 验证样本数
        """
        self.model.eval()
        total_loss = 0.0
        n_samples = 0

        all_p_bin: List[torch.Tensor] = []
        all_y_bin: List[torch.Tensor] = []

        for batch in self.val_loader:
            data, y_cls, y_ret = _unpack_batch(batch)
            data = data.to(self.device)
            y_bin = self.binarize_labels(y_cls, y_ret).to(self.device)
            if y_ret is not None:
                y_ret = y_ret.to(self.device)

            p_bin, ret_pred = self.model(data)
            loss = self.criterion(p_bin, ret_pred, y_bin, y_ret)

            bs = data.size(0)
            total_loss += loss.item() * bs
            n_samples += bs

            all_p_bin.append(p_bin.cpu())
            all_y_bin.append(y_bin.cpu())

        avg_loss = total_loss / max(n_samples, 1)
        self.val_losses.append(avg_loss)

        p_bin_all = torch.cat(all_p_bin)   # [N]
        y_bin_all = torch.cat(all_y_bin)   # [N]

        # 当前校准阈值下指标
        threshold = self.calibrated_threshold
        preds = (p_bin_all >= threshold).float()
        tp = ((preds == 1) & (y_bin_all == 1)).sum().item()
        fp = ((preds == 1) & (y_bin_all == 0)).sum().item()
        fn = ((preds == 0) & (y_bin_all == 1)).sum().item()

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-8)

        self.val_precisions.append(precision)
        self.val_recalls.append(recall)
        self.val_f1s.append(f1)
        self.val_avg_p_bin.append(float(p_bin_all.mean().item()))

        return {
            "loss": avg_loss,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "avg_p_bin": float(p_bin_all.mean().item()),
            "pos_ratio": float(y_bin_all.mean().item()),
            "n_val": n_samples,
        }

    # ── 阈值校准 ──

    @torch.no_grad()
    def calibrate_threshold(
        self,
        target_precision: float = 0.75,
        min_threshold: float = 0.50,
        max_threshold: float = 0.95,
        step: float = 0.025,
    ) -> float:
        """校准决策阈值，使验证集 precision 达到目标值。

        策略：
          扫描 [min_threshold, max_threshold]，步长 step，
          选取满足 precision >= target_precision 的**最低**阈值
          （最低阈值 = 最大召回，在满足精度要求下尽量多选出标的）。
          同时报告该阈值下的选股数及选中均涨幅。

        Args:
            target_precision: 目标精确率（默认 0.75）
            min_threshold: 扫描下界
            max_threshold: 扫描上界
            step: 扫描步长

        Returns:
            校准后的阈值
        """
        self.logger.info("=" * 52)
        self.logger.info(f"阈值校准: 目标 precision ≥ {target_precision:.0%}")
        self.logger.info("-" * 52)

        # 收集验证集预测
        all_p_bin: List[torch.Tensor] = []
        all_y_bin: List[torch.Tensor] = []
        all_y_ret: List[torch.Tensor] = []

        self.model.eval()
        for batch in self.val_loader:
            data, y_cls, y_ret = _unpack_batch(batch)
            data = data.to(self.device)
            y_bin = self.binarize_labels(y_cls, y_ret).to(self.device)

            p_bin, _ = self.model(data)
            all_p_bin.append(p_bin.cpu())
            all_y_bin.append(y_bin.cpu())
            if y_ret is not None:
                all_y_ret.append(y_ret.cpu())

        p_bin_all = torch.cat(all_p_bin).numpy()          # [N]
        y_bin_all = torch.cat(all_y_bin).numpy()          # [N]
        y_ret_all = torch.cat(all_y_ret).numpy() if all_y_ret else None

        # 扫描
        thresholds = np.arange(min_threshold, max_threshold + step, step)
        results: List[Tuple[float, float, float, float, int, float]] = []

        for th in thresholds:
            preds = (p_bin_all >= th).astype(np.float32)
            tp = ((preds == 1) & (y_bin_all == 1)).sum()
            fp = ((preds == 1) & (y_bin_all == 0)).sum()
            fn = ((preds == 0) & (y_bin_all == 1)).sum()
            n_pos = int(preds.sum())

            prec = tp / max(tp + fp, 1)
            rec = tp / max(tp + fn, 1)
            f1 = 2 * prec * rec / max(prec + rec, 1e-8)

            if n_pos > 0 and y_ret_all is not None:
                avg_ret = float(y_ret_all[preds == 1].mean())
            else:
                avg_ret = float("nan")

            results.append((th, prec, rec, f1, n_pos, avg_ret))

        # 打印校准报告
        header = f"{'阈值':>6} | {'精确率':>8} | {'召回率':>8} | {'F1':>6} | {'选股数':>8} | {'均涨幅':>8}"
        self.logger.info(header)
        self.logger.info("-" * 60)
        for th, prec, rec, f1, n, avg_ret in results:
            if prec >= target_precision - 0.02 or n > 0:
                avg_ret_str = f"{avg_ret:>8.4f}" if np.isfinite(avg_ret) else "     nan"
                self.logger.info(
                    f"{th:>6.3f} | {prec:>8.2%} | {rec:>8.2%} | {f1:>6.3f} | {n:>8d} | {avg_ret_str}"
                )

        # 选最佳：满足 precision >= target 的最低阈值
        valid = [r for r in results if r[1] >= target_precision and r[4] > 0]
        if valid:
            best_th, best_prec, best_rec, best_f1, best_n, best_avg_r = valid[0]
        else:
            # 无法达标则取 precision 最高的（此时 >0 选股可能不够）
            best_idx = int(np.argmax([r[1] for r in results]))
            best_th, best_prec, best_rec, best_f1, best_n, best_avg_r = results[best_idx]
            self.logger.warning(
                f"⚠ 无法达 target_precision={target_precision:.0%}，取最高 precision"
            )

        self.calibrated_threshold = best_th
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
        self.logger.info(
            f"✓ 选定阈值={best_th:.3f}  |  "
            f"precision={best_prec:.2%}  recall={best_rec:.2%}  "
            f"选股数={best_n}  均涨幅={avg_ret_str}"
        )
        self.logger.info("=" * 52)
        return best_th

    # ── 完整训练流程 ──

    def train(self):
        """执行完整训练流程。"""
        has_val = self.val_loader is not None
        train_size = len(self.train_loader.dataset)
        val_size = len(self.val_loader.dataset) if has_val else 0
        epochs = self.config.get("EPOCHS", 50)

        self.logger.info(f"开始散户模型训练（总样本: {train_size + val_size:,}, "
                         f"训练: {train_size:,}, 验证: {val_size:,}）")
        self.logger.info(f"损失: RetailLoss(γ_neg={self.config.get('RETAIL_GAMMA_NEG', 4.0)}, "
                         f"λ_reg={self.config.get('RETAIL_LAMBDA_REG', 0.3)})")
        self.logger.info(f"设备: {self.device}")

        for epoch in range(epochs):
            # 训练
            train_loss = self.train_epoch(epoch)
            current_lr = self.optimizer.param_groups[0]["lr"]
            self.logger.info(
                f"Epoch [{epoch + 1}/{epochs}]  "
                f"Train Loss: {train_loss:.4f}  LR: {current_lr:.2e}"
            )

            # 验证
            if has_val:
                metrics = self.validate_epoch()
                self.logger.info(
                    f"  Val Loss: {metrics['loss']:.4f}  "
                    f"Precision: {metrics['precision']:.2%}  "
                    f"Recall: {metrics['recall']:.2%}  "
                    f"F1: {metrics['f1']:.3f}  "
                    f"p_bin avg: {metrics['avg_p_bin']:.3f}"
                )

                # CSV 追加
                self._append_epoch_metrics(epoch, train_loss, metrics)

                # 复用 EarlyStopping
                self.early_stopping(metrics["loss"], self.model)
                if self.early_stopping.early_stop:
                    self.logger.info(f"早停触发（patience={self.early_stopping.patience}）")
                    break

                # 调度器 step
                if self.scheduler is not None:
                    if isinstance(self.scheduler, optim.lr_scheduler.ReduceLROnPlateau):
                        self.scheduler.step(metrics["loss"])
                    else:
                        self.scheduler.step()

        # 加载最佳模型 + 阈值校准
        if has_val and os.path.exists(self.early_stopping.path):
            self.model.load_state_dict(
                torch.load(self.early_stopping.path, map_location=self.device)
            )
            self.logger.info(f"已加载最佳模型: {self.early_stopping.path}")
            self.logger.info("")
            self.calibrate_threshold()
        else:
            self.logger.info("训练完成（无验证集，未做阈值校准）")

    def get_training_history(self) -> dict:
        """返回训练历史字典。"""
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
