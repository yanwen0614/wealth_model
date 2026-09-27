
import numpy as np
import torch
from sklearn.metrics import confusion_matrix


def calculate_latter_half_metrics(labels: torch.Tensor, preds: torch.Tensor,
                                 num_classes: int = 52) -> tuple[float, float]:
    """
    将 52 类映射为二分类（前半=跌=0，后半=涨=1），
    计算"涨"类的精确率和召回率，评估模型预测涨跌方向的准确性。

    参数:
        labels: 真实标签张量 (0..num_classes-1)
        preds: 预测标签张量
        num_classes: 总类别数，默认 52

    返回:
        precision: 涨类精确率 — 模型预测涨的样本中真正涨的比例
        recall: 涨类召回率 — 真正涨的样本中被模型预测为涨的比例
    """
    if isinstance(labels, torch.Tensor):
        labels_np = labels.cpu().numpy()
    else:
        labels_np = np.array(labels)

    if isinstance(preds, torch.Tensor):
        preds_np = preds.cpu().numpy()
    else:
        preds_np = np.array(preds)

    half = num_classes // 2
    bin_true = (labels_np >= half).astype(np.int32)
    bin_pred = (preds_np >= half).astype(np.int32)

    tp = np.sum((bin_true == 1) & (bin_pred == 1))
    fp = np.sum((bin_true == 0) & (bin_pred == 1))
    fn = np.sum((bin_true == 1) & (bin_pred == 0))

    precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
    recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0

    return precision, recall


def calculate_all_class_metrics(labels: torch.Tensor, preds: torch.Tensor, 
                               num_classes: int = 6) -> tuple[list[float], list[float]]:
    """
    计算所有类别的精确率和召回率
    
    参数:
        labels: 真实标签张量
        preds: 预测标签张量
        num_classes: 总类别数
    
    返回:
        precisions: 每个类别的精确率列表
        recalls: 每个类别的召回率列表
    """
    # 确保输入是numpy数组
    if isinstance(labels, torch.Tensor):
        labels_np = labels.cpu().numpy()
    else:
        labels_np = np.array(labels)
    
    if isinstance(preds, torch.Tensor):
        preds_np = preds.cpu().numpy()
    else:
        preds_np = np.array(preds)
    
    # 计算混淆矩阵
    cm = confusion_matrix(labels_np, preds_np, labels=list(range(num_classes)))
    
    precisions = []
    recalls = []
    
    for i in range(num_classes):
        tp = cm[i, i]
        fp = np.sum(cm[:, i]) - tp
        fn = np.sum(cm[i, :]) - tp
        
        # 计算精确率
        if tp + fp == 0:
            precision = 0.0
        else:
            precision = tp / (tp + fp)
        
        # 计算召回率
        if tp + fn == 0:
            recall = 0.0
        else:
            recall = tp / (tp + fn)
        
        precisions.append(precision)
        recalls.append(recall)
    
    return precisions, recalls


def print_detailed_metrics_report(labels: torch.Tensor, preds: torch.Tensor,
                                 num_classes: int = 52):
    """
    打印详细的指标报告 — 二分类（涨/跌）视角
    """
    precision, recall = calculate_latter_half_metrics(labels, preds, num_classes)
    if isinstance(labels, torch.Tensor):
        labels_np = labels.cpu().numpy()
    else:
        labels_np = np.array(labels)
    if isinstance(preds, torch.Tensor):
        preds_np = preds.cpu().numpy()
    else:
        preds_np = np.array(preds)
    half = num_classes // 2
    accuracy = float(np.mean((labels_np >= half) == (preds_np >= half)))

    half = num_classes // 2
    print("=" * 60)
    print("              涨跌二分类指标报告")
    print("=" * 60)
    print(f"类别划分: 前半(跌=0) 0~{half-1}, 后半(涨=1) {half}~{num_classes-1}")
    print(f"涨类精确率(Precision): {precision:.4f}")
    print(f"涨类召回率(Recall):    {recall:.4f}")
    print(f"涨跌二分类准确率:      {accuracy:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    # 测试代码
    print("测试 metrics 模块...")

    # 创建测试数据
    num_classes = 52
    n_samples = 10000

    np.random.seed(42)
    labels = np.random.randint(0, num_classes, n_samples)
    preds = np.random.randint(0, num_classes, n_samples)

    labels_tensor = torch.from_numpy(labels)
    preds_tensor = torch.from_numpy(preds)

    precision, recall = calculate_latter_half_metrics(
        labels_tensor, preds_tensor, num_classes
    )
    print(f"涨类精确率: {precision:.4f}")
    print(f"涨类召回率: {recall:.4f}")

    print_detailed_metrics_report(labels_tensor, preds_tensor, num_classes)
