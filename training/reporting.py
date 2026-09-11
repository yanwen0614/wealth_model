"""训练报告文件输出。"""

import csv
import os

import numpy as np


def save_confusion_matrix(cm: np.ndarray, class_names: list[str], save_dir: str,
                          epoch: int | None = None, logger=None) -> None:
    """保存混淆矩阵 CSV 及文本统计报告。"""
    try:
        os.makedirs(save_dir, exist_ok=True)
        suffix = f"_epoch_{epoch + 1}" if epoch is not None else ""
        csv_path = os.path.join(save_dir, f"confusion_matrix{suffix}.csv")
        txt_path = os.path.join(save_dir, f"confusion_matrix{suffix}.txt")
        with open(csv_path, "w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["真实标签\\预测标签"] + class_names)
            for name, row in zip(class_names, cm):
                writer.writerow([name] + row.tolist())
        total = cm.sum()
        accuracy = cm.trace() / total if total else 0.0
        with open(txt_path, "w", encoding="utf-8") as file:
            file.write("=" * 50 + "\n")
            file.write("                混淆矩阵（文本版）\n")
            file.write("=" * 50 + "\n\n")
            file.write("真实标签\\预测标签" + "".join(f"{name:>8}" for name in class_names) + "\n")
            for name, row in zip(class_names, cm):
                file.write(f"{name:>16}" + "".join(f"{value:>8}" for value in row) + "\n")
            file.write(f"\n总样本数: {total}\n正确分类样本数: {cm.trace()}\n")
            file.write(f"总体准确率: {accuracy:.4f}\n总体错误率: {1 - accuracy:.4f}\n")
            file.write("\n类别 真实样本数 正确分类 错误分类 准确率 错误率\n")
            for name, row in zip(class_names, cm):
                row_total = row.sum()
                correct = cm[class_names.index(name), class_names.index(name)]
                row_accuracy = correct / row_total if row_total else 0.0
                file.write(f"{name} {row_total} {correct} {row_total - correct} "
                           f"{row_accuracy:.4f} {1 - row_accuracy:.4f}\n")
        if logger:
            logger.info(f"混淆矩阵已保存到: {csv_path}, {txt_path}")
    except (OSError, ValueError, ZeroDivisionError) as exc:
        if logger:
            logger.error(f"保存混淆矩阵失败: {exc}")
