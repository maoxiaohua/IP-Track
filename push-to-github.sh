#!/bin/bash

# IP Track System - GitHub 推送脚本

echo "=========================================="
echo "IP Track System - GitHub 推送"
echo "=========================================="
echo ""

# 检查是否已配置远程仓库
if git remote | grep -q origin; then
    echo "✅ 远程仓库已配置"
    git remote -v
else
    echo "请输入你的 GitHub 用户名:"
    read -r GITHUB_USERNAME
    
    echo ""
    echo "正在添加远程仓库..."
    git remote add origin "https://github.com/${GITHUB_USERNAME}/IP-TRACK.git"
    echo "✅ 远程仓库已添加: https://github.com/${GITHUB_USERNAME}/IP-TRACK.git"
fi

echo ""
echo "=========================================="
echo "准备推送代码..."
echo "=========================================="
echo ""

# 显示当前状态
echo "📊 当前状态:"
git log --oneline -5
echo ""

# 推送代码
echo "正在推送到 GitHub..."
echo "注意: 如果提示输入密码，请使用 Personal Access Token"
echo ""

git push -u origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "✅ 推送成功！"
    echo "=========================================="
    echo ""
    echo "访问你的仓库:"
    git remote get-url origin | sed 's/\.git$//'
else
    echo ""
    echo "=========================================="
    echo "❌ 推送失败"
    echo "=========================================="
    echo ""
    echo "可能的原因:"
    echo "1. GitHub 仓库尚未创建"
    echo "2. 认证失败（需要 Personal Access Token）"
    echo "3. 网络连接问题"
    echo ""
    echo "请查看 GITHUB_PUSH_GUIDE.md 获取详细说明"
fi
