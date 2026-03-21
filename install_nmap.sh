#!/bin/bash
# 安装nmap并重启服务

echo "=========================================="
echo "安装nmap并重启IP-Track后端服务"
echo "=========================================="
echo ""

cd /opt/IP-Track

echo "步骤 1/4: 停止当前服务..."
sudo docker compose down
if [ $? -eq 0 ]; then
    echo "✅ 服务已停止"
else
    echo "❌ 停止服务失败"
    exit 1
fi
echo ""

echo "步骤 2/4: 重新构建backend镜像（包含nmap）..."
sudo docker compose build backend
if [ $? -eq 0 ]; then
    echo "✅ 镜像构建完成"
else
    echo "❌ 镜像构建失败"
    exit 1
fi
echo ""

echo "步骤 3/4: 启动所有服务..."
sudo docker compose up -d
if [ $? -eq 0 ]; then
    echo "✅ 服务已启动"
else
    echo "❌ 启动服务失败"
    exit 1
fi
echo ""

echo "步骤 4/4: 等待服务就绪..."
sleep 10

# 验证nmap安装
echo ""
echo "验证nmap安装状态："
sudo docker exec iptrack-backend nmap --version 2>&1 | head -1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ nmap安装成功！"
else
    echo ""
    echo "❌ nmap验证失败"
    exit 1
fi

echo ""
echo "=========================================="
echo "安装完成"
echo "=========================================="
echo ""
echo "现在OS检测会更准确："
echo "- TTL=64 → Linux/Unix"
echo "- TTL=128 → Windows"
echo "- nmap深度检测 → Windows 10/11, Ubuntu 20.04/22.04, etc."
echo ""
echo "建议: 重新扫描IPAM子网以更新OS信息"
echo ""
