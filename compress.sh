#!/bin/bash

# 简单的 Git 工作区打包脚本

echo "========================================="
echo "Git 工作区打包工具"
echo "========================================="

# 检查是否在 Git 仓库中
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "错误: 当前目录不是 Git 仓库"
    exit 1
fi

# 获取 Git 信息
repo_name=$(basename $(git rev-parse --show-toplevel))
current_branch=$(git branch --show-current)
latest_commit=$(git log -1 --format="%h")
commit_date=$(git log -1 --format="%cd" --date=short)

echo "仓库信息:"
echo "  仓库名称: $repo_name"
echo "  当前分支: $current_branch"
echo "  最新提交: $latest_commit ($commit_date)"
echo ""

# 生成输出文件名
OUTPUT_FILE="git_backup_${repo_name}_${current_branch}_${commit_date}_${latest_commit}.tar.gz"

echo "打包策略: 所有已跟踪文件"
echo ""

# 获取已跟踪文件列表
TEMP_LIST=$(mktemp)
git ls-files > "$TEMP_LIST"

# 检查文件数量
FILE_COUNT=$(wc -l < "$TEMP_LIST" | tr -d ' ')
if [ "$FILE_COUNT" -eq "0" ]; then
    echo "错误: 没有找到要打包的文件"
    rm -f "$TEMP_LIST"
    exit 1
fi

echo "找到 $FILE_COUNT 个文件"
echo ""

# 显示部分文件
echo "打包文件示例（前5个）:"
head -5 "$TEMP_LIST" | while read -r file; do
    echo "  - $file"
done
if [ "$FILE_COUNT" -gt 5 ]; then
    echo "  ... 还有 $((FILE_COUNT - 5)) 个文件"
fi
echo ""

# 执行打包
echo "正在打包到: $OUTPUT_FILE"
echo ""

if tar -czf "$OUTPUT_FILE" --files-from="$TEMP_LIST"; then
    echo "✅ 打包成功!"
    echo ""
    echo "文件: $OUTPUT_FILE"
    echo "大小: $(du -h "$OUTPUT_FILE" | cut -f1)"
    echo "文件数: $FILE_COUNT"
else
    echo "❌ 打包失败!"
    rm -f "$TEMP_LIST"
    exit 1
fi

# 清理
rm -f "$TEMP_LIST"

echo ""
echo "✨ 打包完成!"
echo "========================================="
