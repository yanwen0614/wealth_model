import torch
import torch.nn as nn
from typing import Optional
import numpy as np
import logging

# 创建logger
logger = logging.getLogger(__name__)

class HalfClassWeightedCrossEntropy(nn.Module):
    """
    针对前后半类的加权交叉熵损失函数
    
    核心思想：
    - 当后半类被误判为前半类时，给予大罚项（严重错误）
    - 当后半类内部分错时，给予较少罚项（轻微错误）
    - 前半类的错误使用标准惩罚
    
    参数:
        num_classes: 总类别数（6或8）
        large_penalty: 后半类被误判为前半类的惩罚倍数（默认5.0）
        small_penalty: 后半类内部分错的惩罚倍数（默认0.5）
        reduction: 损失聚合方式 ('mean', 'sum', 'none')
    """
    def __init__(self, num_classes: int = 6, 
                 large_penalty: float = 1.5, 
                 class_weights=None,
                 reduction: str = 'mean'):
        super(HalfClassWeightedCrossEntropy, self).__init__()
        self.num_classes = num_classes
        self.large_penalty = large_penalty
        self.reduction = reduction
        
        # 根据类别数确定前后半类的划分
        # 6分类：前半类=0,1,2，后半类=3,4,5
        # 8分类：前半类=0,1,2,3，后半类=4,5,6,7
        self.first_half_end = num_classes // 2
        
        if class_weights is not None:
            self.ce = nn.CrossEntropyLoss(weight=class_weights, reduction='none')
        else:
            self.ce = nn.CrossEntropyLoss(reduction='none')
            
        # 初始化logger
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        参数:
            inputs: 模型输出 logits，形状 (batch_size, num_classes)
            targets: 真实标签，形状 (batch_size,)
        
        返回:
            加权后的损失值
        """
        # 计算标准交叉熵损失（逐样本）
        standard_loss = self.ce(inputs, targets)
        
        # 获取预测类别
        pred_classes = torch.argmax(inputs, dim=1)
        
        # 判断真实标签是否属于后半类
        targets_is_latter_half = targets >= self.first_half_end

        # 判断真实标签是否属于前半类
        targets_is_first_half = targets < self.first_half_end
        
        # 判断预测类别是否属于前半类
        preds_is_first_half = pred_classes < self.first_half_end
        
        # 判断预测类别是否属于后半类
        preds_is_latter_half = pred_classes >= self.first_half_end
        
        # 创建权重向量，默认为1.0（标准惩罚）
        weights = torch.ones_like(standard_loss) * torch.sqrt((abs(pred_classes - targets) + 1))
        self.logger.debug("pred_classes %s", pred_classes)
        self.logger.debug("targets %s", targets)
        self.logger.debug("weights %s", weights)
        # 情况1：前半类被误判为后半类 -> 大罚项
        # 条件：真实标签是前半类 AND 预测是后半类 AND 预测错误
        case1_mask = targets_is_first_half & preds_is_latter_half & (pred_classes != targets)
        self.logger.debug("case1_mask %s", case1_mask)
        weights[case1_mask] = weights[case1_mask] * self.large_penalty

        self.logger.debug("weights %s", weights)
        
        # 应用权重
        weighted_loss = standard_loss * weights
        
        # 根据reduction方式返回
        if self.reduction == 'mean':
            return weighted_loss.mean()
        elif self.reduction == 'sum':
            return weighted_loss.sum()
        else:  # 'none'
            return weighted_loss


def create_v_shape_weights(num_classes, edge_weight=5.0, center_weight=1.0):
    """
    创建V型权重分布：两端权重高，中间权重低
    
    Args:
        num_classes: 类别数量
        edge_weight: 边缘类别的权重
        center_weight: 中心类别的权重
    
    Returns:
        class_weights: shape为(num_classes,)的权重数组
    """
    # 计算中心点位置
    if num_classes % 2 ==1:
        center = num_classes / 2
    else:
        center = (num_classes - 1) / 2
    
    # 生成类别索引
    indices = np.arange(num_classes)
    
    # 计算每个类别到中心的距离（归一化到0-1）
    distances = np.abs(indices - center) / center
    
    # 线性插值：距离越大（越靠近边缘），权重越高
    class_weights = center_weight + (edge_weight - center_weight) * distances
    
    return class_weights.astype(np.float32)

if __name__ == "__main__":
    # 测试代码
    print("测试 HalfClassWeightedCrossEntropy...")
    # 配置测试日志
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 6分类测试
    num_classes = 6
    batch_size = 10
    
    # 创建模拟数据
    torch.manual_seed(42)
    inputs = torch.randn(batch_size, num_classes)
    logger.debug("inputs %s", inputs)
    targets = torch.randint(0, num_classes, (batch_size,))
    logger.debug("targets %s", targets)
    class_weights = create_v_shape_weights(6)
    logger.debug("class_weights %s", class_weights)
    # 创建损失函数
    criterion = HalfClassWeightedCrossEntropy(num_classes=6, large_penalty=5.0, small_penalty=1.5,class_weights=torch.from_numpy(class_weights))
    
    # 计算损失
    loss = criterion(inputs, targets)
    print(f"6分类损失: {loss.item():.4f}")
    logger.info(f"6分类损失: {loss.item():.4f}")
    
    # 对比标准交叉熵
    standard_ce = nn.CrossEntropyLoss(reduction="none")
    standard_loss = standard_ce(inputs, targets)
    print(f"标准交叉熵损失(class_weights): {standard_loss}")
    logger.debug(f"标准交叉熵损失(class_weights): {standard_loss}")
    
        # 对比标准交叉熵
    standard_ce = nn.CrossEntropyLoss()
    standard_loss = standard_ce(inputs, targets)
    print(f"标准交叉熵损失: {standard_loss.item():.4f}")
    logger.info(f"标准交叉熵损失: {standard_loss.item():.4f}")


    # 8分类测试
    print("\n测试 8分类...")
    logger.info("\n测试 8分类...")
    num_classes = 8
    inputs_8 = torch.randn(batch_size, num_classes)
    targets_8 = torch.randint(0, num_classes, (batch_size,))
    
    criterion_8 = HalfClassWeightedCrossEntropy(num_classes=8, large_penalty=5.0, small_penalty=1.5)
    loss_8 = criterion_8(inputs_8, targets_8)
    print(f"8分类损失: {loss_8.item():.4f}")
    logger.info(f"8分类损失: {loss_8.item():.4f}")
    
    print("\n测试完成！")
    logger.info("\n测试完成！")
