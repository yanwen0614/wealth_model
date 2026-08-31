import torch
import torch.nn as nn
import torch.nn.functional as F

class EMDLoss(nn.Module):
    """
    Earth Mover's Distance (EMD) Loss for Ordinal Regression.
    在有序分类中，EMD 等价于两个累积分布函数 (CDF) 之间的距离。
    
    支持标签平滑策略：
    - 可以通过参数控制是否开启
    - 最多往相邻2阶类别迁移
    - 边缘类别（最小和最大类别）不进行迁移
    """
    def __init__(self, num_classes=10, p=2, label_smoothing=False, smooth_eps=0.1):
        """
        Args:
            num_classes (int): 类别数量
            p (int): 范数 (p-norm). 1 for L1 distance, 2 for L2 distance (Squared EMD).
                     通常使用 p=2 (Squared EMD) 效果较好，类似 MSE.
            label_smoothing (bool): 是否开启标签平滑
            smooth_eps (float): 标签平滑的强度，取值范围 (0, 1)
                                表示将多少比例的概率从真实标签迁移到相邻类别
        """
        super(EMDLoss, self).__init__()
        self.num_classes = num_classes
        self.p = p
        self.label_smoothing = label_smoothing
        self.smooth_eps = smooth_eps
        
        # 预计算每个类别的平滑权重矩阵
        if self.label_smoothing and self.num_classes > 1:
            self.smooth_weights = self._compute_smooth_weights()

    def _compute_smooth_weights(self):
        """
        计算标签平滑的权重矩阵 (优化版)
        """
        # 初始化单位矩阵
        weights = torch.eye(self.num_classes)
        
        # 1. 处理二分类特殊情况 (直接交换 eps)
        if self.num_classes == 2:
            weights[0, 0] -= self.smooth_eps
            weights[0, 1] += self.smooth_eps
            weights[1, 1] -= self.smooth_eps
            weights[1, 0] += self.smooth_eps
            return weights

        # 2. 处理多分类情况 (>=3)
        # 定义平滑规则: {距离: 权重比例}
        # 距离1分配 2/3，距离2分配 1/3
        dist_rules = {1: 2/3, 2: 1/3}

        for cls in range(self.num_classes):
            used_eps = 0.0  # 记录实际分配出去的权重
            
            for dist, ratio in dist_rules.items():
                # 计算当前距离应分配的总权重
                dist_weight = self.smooth_eps * ratio
                
                # 确定左右邻居索引
                left, right = cls - dist, cls + dist
                neighbors = []
                if left >= 0: neighbors.append(left)
                if right < self.num_classes: neighbors.append(right)
                
                # 如果没有有效邻居，跳过
                if not neighbors:
                    continue
                    
                # 计算每个邻居分到的权重
                # 逻辑：如果左右都存在，平分权重；如果只存在一边(边缘)，独享权重
                per_neighbor_weight = dist_weight / len(neighbors)
                
                for n_idx in neighbors:
                    weights[cls, n_idx] += per_neighbor_weight
                    used_eps += per_neighbor_weight
            
            # 从对角线减去实际分配的权重，保证行和为 1
            weights[cls, cls] -= used_eps
                
        return weights

    def _apply_label_smoothing(self, targets):
        """
        对真实标签应用标签平滑
        
        Args:
            targets: 真实标签索引 (Batch_Size,)
        
        Returns:
            smoothed_targets: 平滑后的标签分布 (Batch_Size, Num_Classes)
        """
        # 转换为 one-hot 编码
        target_onehot = F.one_hot(targets, num_classes=self.num_classes).float()
        
        # 应用标签平滑
        smoothed_targets = torch.matmul(target_onehot, self.smooth_weights)
        
        return smoothed_targets

    def forward(self, logits, targets):
        """
        Args:
            logits: 模型输出 (Batch_Size, Num_Classes)，未经过 Softmax
            targets: 真实标签索引 (Batch_Size,)，例如 [2, 5, 0...]
        
        Returns:
            loss: 标量损失值
        """
        # 1. 将 Logits 转换为概率分布 (Softmax)
        probs = F.softmax(logits, dim=1)
        
        # 2. 计算预测值的累积分布函数 (CDF)
        # cumsum 沿着类别维度 (dim=1) 累加
        pred_cdf = torch.cumsum(probs, dim=1)
        
        # 3. 构建真值的累积分布函数 (CDF)
        if self.label_smoothing and self.num_classes > 1:
            # 应用标签平滑
            target_dist = self._apply_label_smoothing(targets)
        else:
            # 不使用标签平滑，直接转换为 one-hot 编码
            target_dist = F.one_hot(targets, num_classes=self.num_classes).float()
        
        # 计算真值的 CDF
        target_cdf = torch.cumsum(target_dist, dim=1)
        
        # 4. 计算两个 CDF 之间的距离
        if self.p == 1:
            loss = torch.mean(torch.abs(pred_cdf - target_cdf))
        elif self.p == 2:
            loss = torch.mean(torch.pow(pred_cdf - target_cdf, 2))
        else:
            loss = torch.mean(torch.pow(torch.abs(pred_cdf - target_cdf), self.p))
            
        return loss

    def to(self, device):
        """
        将损失函数的参数移动到指定设备
        
        Args:
            device: 目标设备，可以是字符串（如"cuda"、"cpu"）或torch.device对象
        
        Returns:
            self: 移动后的损失函数实例
        """
        self.device = torch.device(device)
        
        # 如果使用了标签平滑，将平滑权重矩阵移动到指定设备
        if self.label_smoothing and self.num_classes > 1:
            self.smooth_weights = self.smooth_weights.to(self.device)
            
        return self


# --- 使用示例 ---
if __name__ == "__main__":
    # 假设有 5 个有序类别 (0, 1, 2, 3, 4)
    num_classes = 5
    batch_size = 3
    
    # 初始化 Loss（不使用标签平滑）
    emd_loss_no_smooth = EMDLoss(num_classes=num_classes, p=2, label_smoothing=False)
    
    # 初始化 Loss（使用标签平滑）
    emd_loss_with_smooth = EMDLoss(num_classes=num_classes, p=2, label_smoothing=True, smooth_eps=0.1)
    
    # 模拟模型输出 (Logits)
    logits = torch.tensor([
        [5.0, 1.0, 0.0, 0.0, 0.0], 
        [0.0, 0.0, 0.0, 1.0, 5.0],
        [1.0, 1.0, 1.0, 1.0, 1.0]
    ], requires_grad=True)
    
    # 真实标签
    targets = torch.tensor([0, 4, 2]) # 分别对应上述三个样本
    
    # 计算 Loss（不使用标签平滑）
    loss_no_smooth = emd_loss_no_smooth(logits, targets)
    print(f"Loss without label smoothing: {loss_no_smooth.item()}")
    
    # 计算 Loss（使用标签平滑）
    loss_with_smooth = emd_loss_with_smooth(logits, targets)
    print(f"Loss with label smoothing: {loss_with_smooth.item()}")
    
    # 查看标签平滑效果
    if emd_loss_with_smooth.label_smoothing:
        print("\n标签平滑权重矩阵:")
        print(emd_loss_with_smooth.smooth_weights)
        
        # 查看单个标签的平滑效果
        sample_target = torch.tensor([2])  # 中间类别
        smoothed = emd_loss_with_smooth._apply_label_smoothing(sample_target)
        print(f"\n类别 2 平滑后的分布: {smoothed}")
        print(f"总和: {torch.sum(smoothed):.4f}")
        
        # 边缘类别不进行平滑
        edge_target = torch.tensor([0])  # 边缘类别
        smoothed_edge = emd_loss_with_smooth._apply_label_smoothing(edge_target)
        print(f"\n类别 0（边缘）平滑后的分布: {smoothed_edge}")
        print(f"总和: {torch.sum(smoothed_edge):.4f}")
    
    # 反向传播测试
    loss_with_smooth.backward()
    print("\nGradients calculated successfully.")
