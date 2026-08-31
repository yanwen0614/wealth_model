import os
import numpy as np
from collections import Counter
import matplotlib.pyplot as plt
from data.npz_data_load import DataConfig
from tqdm import tqdm

def analyze_label_distribution(config: DataConfig):
    """
    分析离散化前label的分布情况
    """
    print("=== 分析离散化前label的分布情况 ===")
    
    # 获取所有npz文件
    npz_files = sorted([f for f in os.listdir(config.npz_dir) if f.endswith(".npz")])
    print(f"找到 {len(npz_files)} 个NPZ文件")
    
    # 统计所有label
    all_labels = []
    total_samples = 0
    
    for i, file_name in tqdm(enumerate(npz_files),total=len(npz_files)):
        file_path = os.path.join(config.npz_dir, file_name)
        
        with np.load(file_path) as f:
            labels = f["labels"]
            
            # 处理不同形状的label数据
            if len(labels.shape) == 2:
                # 如果是二维数组，取最后一列（如npz_data_load2.py中的处理方式）
                if labels.shape[1] > 1:
                    # 取最后一维的最后一个值
                    processed_labels = labels[:, :, -1].sum(axis=1) if len(labels.shape) == 3 else labels[:, -1]
                else:
                    processed_labels = labels.flatten()
            elif len(labels.shape) == 3:
                # 三维数组，按npz_data_load2.py中的处理方式
                processed_labels = np.sum(labels[:, :, -1], axis=1)
            else:
                processed_labels = labels.flatten()
            
            all_labels.extend(processed_labels.tolist())
            total_samples += len(processed_labels)
            
            # print(f"处理文件 {i+1}/{len(npz_files)}: {file_name}, 样本数: {len(processed_labels)}")
    
    # 计算分布
    all_labels = (np.array(all_labels)*1000).astype(int)
    label_counter = Counter((all_labels/100).astype(int))
    sorted_labels = sorted(label_counter.items())
    
    print(f"\n=== 离散化前label分布统计结果 ===")
    print(f"总样本数: {total_samples}")
    print(f"不同label值的数量: {len(label_counter)}")
    # print("\n详细分布:")
    
    # # 计算每个label的占比
    # for label, count in sorted_labels:
    #     percentage = (count / total_samples) * 100
    #     print(f"  label值: {label:>10.6f} | 数量: {count:>8d} | 占比: {percentage:>6.2f}%")
    
    # 统计最小值、最大值、平均值
    if len(all_labels) > 0:
        print(f"\n统计指标:")
        print(f"  最小值: {np.min(all_labels):.6f}")
        print(f"  最大值: {np.max(all_labels):.6f}")
        print(f"  平均值: {np.mean(all_labels):.6f}")
        print(f"  中位数: {np.median(all_labels):.6f}")
        print(f"  标准差: {np.std(all_labels):.6f}")
    
        # 显示离散化边界
        print(f"\n=== 离散化边界（DataConfig.bins） ===")
        print(f"边界值: {config.bins}")
        print(f"区间数量: {len(config.bins) - 1}")
        
        # 显示每个区间的样本分布
        print(f"\n=== 离散化后区间分布预测 ===")
        bins = \
        [
            np.linspace(-25,25,51)*10,
            ]
        for b in bins:
            print("----------------------------------------")
            # 使用np.digitize计算每个label对应的区间
            intervals = np.digitize(all_labels, b)
            
            # 统计区间分布
            interval_counter = Counter(intervals)
            sorted_intervals = sorted(interval_counter.items())
            
            for interval, count in sorted_intervals:
                percentage = (count / total_samples) * 100
                if interval == 0:
                    range_str = f"(-∞, {b[0]:.6f}]"
                elif interval == len(b):
                    range_str = f"({b[-1]:.6f}, +∞)"
                else:
                    range_str = f"({b[interval-1]:.6f}, {b[interval]:.6f}]"
                print(f"  区间 {interval:2d}: {range_str:<30} | 数量: {count:>8d} | 占比: {percentage:>6.2f}%")
    

  
        visualize_label_distribution(all_labels, config.bins)
    
    return label_counter


def visualize_label_distribution(labels, bins):
    """
    Visualize label distribution
    """
    print("\n=== Generating visualization plots ===")
    
    # Create output directory
    output_dir = "label_distribution_plots"
    os.makedirs(output_dir, exist_ok=True)
    
    # Convert to numpy array
    labels_np = np.array(labels)

    # Sample 10% of data for faster visualization
    labels_np = sampled_arr = np.random.choice(labels_np, size=int(len(labels_np)*0.1), replace=False)
    
    # Calculate mean and standard error (using standard deviation as estimate)
    mean_val = np.mean(labels_np)
    std_val = np.std(labels_np)
    # Calculate axis range: mean ± 3*std
    x_min = mean_val - 3 * std_val
    x_max = mean_val + 3 * std_val
    
    # 1. Histogram + Density Plot
    plt.figure(figsize=(12, 6))
    
    # Histogram
    n, bins_hist, patches = plt.hist(labels_np, bins=100, density=True, alpha=0.6, color='g', label='Histogram')
    
    # Kernel Density Estimation
    from scipy.stats import gaussian_kde
    kde = gaussian_kde(labels_np)
    xvals = np.linspace(x_min, x_max, 1000)
    plt.plot(xvals, kde(xvals), 'r-', linewidth=2, label='Kernel Density Estimate')
    
    # Add discretization boundary lines
    for bin_val in bins:
        if x_min <= bin_val <= x_max:  # Only show boundaries within the axis range
            plt.axvline(x=bin_val, color='b', linestyle='--', alpha=0.5, label='Discretization Boundary' if bin_val == bins[0] else "")
    
    plt.title('Label Distribution - Histogram and Density Plot', fontsize=14)
    plt.xlabel('Label Value', fontsize=12)
    plt.ylabel('Density/Frequency', fontsize=12)
    plt.xlim(x_min, x_max)
    plt.grid(axis='y', alpha=0.75)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'label_histogram_density.png'), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {os.path.join(output_dir, 'label_histogram_density.png')}")
    
    # 2. Box Plot
    plt.figure(figsize=(10, 6))
    box = plt.boxplot(labels_np, vert=False, patch_artist=True, labels=['Label Values'])
    
    # Set colors
    colors = ['lightblue']
    for patch, color in zip(box['boxes'], colors):
        patch.set_facecolor(color)
    
    # Add discretization boundary lines
    y_min, y_max = plt.ylim()
    for bin_val in bins:
        if x_min <= bin_val <= x_max:  # Only show boundaries within the axis range
            plt.axvline(x=bin_val, color='r', linestyle='--', alpha=0.5)
    
    plt.title('Label Distribution - Box Plot', fontsize=14)
    plt.xlabel('Label Value', fontsize=12)
    plt.xlim(x_min, x_max)
    plt.grid(axis='x', alpha=0.75)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'label_boxplot.png'), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {os.path.join(output_dir, 'label_boxplot.png')}")
    
    # 3. Cumulative Distribution Function Plot
    plt.figure(figsize=(12, 6))
    sorted_labels = np.sort(labels_np)
    cdf = np.arange(1, len(sorted_labels)+1) / len(sorted_labels)
    
    plt.plot(sorted_labels, cdf, 'b-', linewidth=2, label='Cumulative Distribution Function')
    
    # Add discretization boundary lines
    for bin_val in bins:
        if x_min <= bin_val <= x_max:  # Only show boundaries within the axis range
            plt.axvline(x=bin_val, color='r', linestyle='--', alpha=0.5)
            # Calculate cumulative probability for this boundary
            prob = np.mean(labels_np <= bin_val)
            plt.scatter(bin_val, prob, color='r', s=50, zorder=5)
            plt.text(bin_val, prob + 0.02, f'{prob:.2f}', ha='center', va='bottom', color='r')
    
    plt.title('Label Distribution - Cumulative Distribution Function', fontsize=14)
    plt.xlabel('Label Value', fontsize=12)
    plt.ylabel('Cumulative Probability', fontsize=12)
    plt.xlim(x_min, x_max)
    plt.grid(alpha=0.75)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'label_cdf.png'), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {os.path.join(output_dir, 'label_cdf.png')}")
    
    # 4. Discretized Interval Distribution Bar Plot
    plt.figure(figsize=(12, 6))
    intervals = np.digitize(labels_np, bins)
    interval_counts = Counter(intervals)
    
    # Prepare data
    interval_labels = []
    interval_values = []
    for interval in sorted(interval_counts.keys()):
        count = interval_counts[interval]
        interval_values.append(count)
        
        if interval == 0:
            label = f"(-∞, {bins[0]:.4f}]"
        elif interval == len(bins):
            label = f"({bins[-1]:.4f}, +∞)"
        else:
            label = f"({bins[interval-1]:.4f}, {bins[interval]:.4f}]"
        interval_labels.append(label)
    
    # Plot bar chart
    bars = plt.bar(range(len(interval_labels)), interval_values, color='skyblue')
    
    # Add value labels
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2., height,
                 f'{height}\n({height/len(labels_np)*100:.1f}%)',
                 ha='center', va='bottom')
    
    plt.title('Discretized Interval Distribution', fontsize=14)
    plt.xlabel('Interval', fontsize=12)
    plt.ylabel('Number of Samples', fontsize=12)
    plt.xticks(range(len(interval_labels)), interval_labels, rotation=45, ha='right')
    plt.grid(axis='y', alpha=0.75)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'label_discretized_dist.png'), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved: {os.path.join(output_dir, 'label_discretized_dist.png')}")
    
    print(f"\nAll visualization plots have been saved to directory: {output_dir}")


if __name__ == "__main__":
    # 创建配置
    config = DataConfig(
        npz_dir="./processed_data_train",  # 替换为实际数据目录
        bins=np.linspace(-25,25,51)*10
    )
    
    # 检查数据目录是否存在
    if not os.path.exists(config.npz_dir):
        print(f"错误: 数据目录 {config.npz_dir} 不存在!")
        print("请先运行数据处理脚本生成NPZ文件，或者修改config.npz_dir为正确的路径")
    else:
        # 执行分析
        analyze_label_distribution(config)