import torch
import numpy as np
from sklearn.metrics import confusion_matrix
from typing import Tuple, List


def calculate_latter_half_metrics(labels: torch.Tensor, preds: torch.Tensor, 
                                 num_classes: int = 6, weight_type: str = 'equal') -> Tuple[float, float]:
    """
    计算后半类的加权精确率和加权召回率
    
    参数:
        labels: 真实标签张量
        preds: 预测标签张量
        num_classes: 总类别数，默认为6
        weight_type: 加权类型，'equal'为等权重，'sample'为按样本数加权
    
    返回:
        latter_half_weighted_precision: 后半类加权精确率
        latter_half_weighted_recall: 后半类加权召回率
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
    
    # 初始化存储每个类别指标的列表
    precisions = []
    recalls = []
    class_sample_counts = []
    
    # 计算每个类别的精确率和召回率
    for i in range(num_classes):
        # TP: 正确预测为该类的样本数
        tp = cm[i, i]
        
        # FP: 预测为该类但实际不是的样本数
        fp = np.sum(cm[:, i]) - tp
        
        # FN: 实际是该类但预测为其他类的样本数
        fn = np.sum(cm[i, :]) - tp
        
        # TN: 既不是该类也没有预测为该类的样本数
        tn = np.sum(cm) - tp - fp - fn
        
        # 计算精确率 (Precision)
        if tp + fp == 0:
            precision = 0.0
        else:
            precision = tp / (tp + fp)
        
        # 计算召回率 (Recall)
        if tp + fn == 0:
            recall = 0.0
        else:
            recall = tp / (tp + fn)
        
        precisions.append(precision)
        recalls.append(recall)
        class_sample_counts.append(np.sum(cm[i, :]))  # 该类别的真实样本数
    
    # 确定后半类的索引（假设类别从0开始编号）
    # 对于6分类：前半类=0,1,2，后半类=3,4,5
    first_half_end = num_classes // 2  # 前半类结束索引（不包含）
    latter_half_indices = list(range(first_half_end, num_classes))
    
    # 提取后半类的指标
    latter_half_precisions = [precisions[i] for i in latter_half_indices]
    latter_half_recalls = [recalls[i] for i in latter_half_indices]
    latter_half_sample_counts = [class_sample_counts[i] for i in latter_half_indices]
    
    # 计算加权平均值
    if weight_type == 'equal':
        # 等权重
        latter_half_weighted_precision = np.mean(latter_half_precisions)
        latter_half_weighted_recall = np.mean(latter_half_recalls)
    
    elif weight_type == 'sample':
        # 按样本数加权
        total_samples = np.sum(latter_half_sample_counts)
        if total_samples > 0:
            weights = [count / total_samples for count in latter_half_sample_counts]
            latter_half_weighted_precision = np.average(latter_half_precisions, weights=weights)
            latter_half_weighted_recall = np.average(latter_half_recalls, weights=weights)
        else:
            latter_half_weighted_precision = 0.0
            latter_half_weighted_recall = 0.0
    
    else:
        raise ValueError(f"不支持的weight_type: {weight_type}。请使用 'equal' 或 'sample'")
    
    return float(latter_half_weighted_precision), float(latter_half_weighted_recall)


def calculate_all_class_metrics(labels: torch.Tensor, preds: torch.Tensor, 
                               num_classes: int = 6) -> Tuple[List[float], List[float]]:
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
                                 num_classes: int = 6, weight_type: str = 'equal'):
    """
    打印详细的指标报告
    
    参数:
        labels: 真实标签张量
        preds: 预测标签张量
        num_classes: 总类别数
        weight_type: 加权类型
    """
    # 计算所有类别的指标
    precisions, recalls = calculate_all_class_metrics(labels, preds, num_classes)
    
    # 计算后半类加权指标
    latter_half_precision, latter_half_recall = calculate_latter_half_metrics(
        labels, preds, num_classes, weight_type
    )
    
    print("=" * 60)
    print("                   分类指标详细报告")
    print("=" * 60)
    
    # 打印每个类别的指标
    print("\n每个类别的指标:")
    print(f"{'类别':<6} {'精确率':<10} {'召回率':<10} {'样本数':<10}")
    print("-" * 40)
    
    # 计算每个类别的样本数
    if isinstance(labels, torch.Tensor):
        labels_np = labels.cpu().numpy()
    else:
        labels_np = np.array(labels)
    
    for i in range(num_classes):
        sample_count = np.sum(labels_np == i)
        print(f"{i:<6} {precisions[i]:<10.4f} {recalls[i]:<10.4f} {sample_count:<10}")
    
    # 打印后半类指标
    print("\n后半类加权指标:")
    print(f"加权精确率: {latter_half_precision:.4f}")
    print(f"加权召回率: {latter_half_recall:.4f}")
    print(f"加权类型: {weight_type}")
    
    # 打印前后半类划分信息
    first_half_end = num_classes // 2
    print(f"\n类别划分:")
    print(f"前半类: {list(range(first_half_end))}")
    print(f"后半类: {list(range(first_half_end, num_classes))}")
    print("=" * 60)


if __name__ == "__main__":
    # 测试代码
    print("测试 metrics 模块...")
    
    # 创建测试数据
    num_classes = 6
    n_samples = 1000
    
    # 生成随机标签和预测
    np.random.seed(42)
    labels = np.random.randint(0, num_classes, n_samples)
    preds = np.random.randint(0, num_classes, n_samples)
    
    # 转换为torch张量
    labels_tensor = torch.from_numpy(labels)
    preds_tensor = torch.from_numpy(preds)
    
    # 测试等权重
    print("\n1. 等权重测试:")
    precision_eq, recall_eq = calculate_latter_half_metrics(
        labels_tensor, preds_tensor, num_classes, weight_type='equal'
    )
    print(f"后半类等权重精确率: {precision_eq:.4f}")
    print(f"后半类等权重召回率: {recall_eq:.4f}")
    
    # 测试样本权重
    print("\n2. 样本权重测试:")
    precision_sample, recall_sample = calculate_latter_half_metrics(
        labels_tensor, preds_tensor, num_classes, weight_type='sample'
    )
    print(f"后半类样本权重精确率: {precision_sample:.4f}")
    print(f"后半类样本权重召回率: {recall_sample:.4f}")
    
    # 打印详细报告
    print("\n3. 详细报告:")
    print_detailed_metrics_report(labels_tensor, preds_tensor, num_classes, weight_type='equal')
