#!/bin/bash
# 快速测试脚本 - 验证DNS、SNMP、nmap配置

echo "=========================================="
echo "IP-Track IPAM功能快速测试"
echo "=========================================="
echo ""

# 测试1: 检查nmap
echo "1. 检查nmap安装状态..."
if command -v nmap &> /dev/null; then
    echo "   ✅ nmap已安装: $(nmap --version | head -1)"
else
    echo "   ❌ nmap未安装"
    echo "   建议: 修改backend/Dockerfile添加nmap，然后重建镜像"
fi
echo ""

# 测试2: 检查DNS工具
echo "2. 检查DNS工具..."
if command -v nslookup &> /dev/null; then
    echo "   ✅ nslookup可用"
else
    echo "   ⚠️  nslookup不可用（通常已内置）"
fi
echo ""

# 测试3: 检查SNMP工具
echo "3. 检查SNMP工具..."
if command -v snmpget &> /dev/null; then
    echo "   ✅ snmpget已安装"
else
    echo "   ⚠️  snmpget未安装（可选）"
    echo "   安装方法: apt-get install -y snmp"
fi
echo ""

# 测试4: Python诊断工具
echo "4. 运行Python诊断工具..."
if [ -f "/app/diagnose_ipam.py" ]; then
    echo "   ✅ 诊断工具已就绪"
    echo "   运行方法: python /app/diagnose_ipam.py"
else
    echo "   ❌ 诊断工具不存在"
fi
echo ""

# 测试5: 测试DNS PTR（如果提供IP）
if [ -n "$1" ]; then
    echo "5. 测试DNS PTR查询: $1"
    nslookup "$1" 2>&1 | grep -E "name =|can't find" | head -1
else
    echo "5. 跳过DNS PTR测试（未提供IP地址）"
    echo "   使用方法: ./quick_test.sh 10.101.35.10"
fi
echo ""

echo "=========================================="
echo "测试完成"
echo "=========================================="
echo ""
echo "下一步:"
echo "1. 如需精确OS检测，安装nmap: 修改Dockerfile → docker-compose build backend"
echo "2. 如需测试SNMP，运行: python /app/diagnose_ipam.py"
echo "3. 如需配置DNS PTR，参考: IPAM_FEATURES_GUIDE.md"
echo ""
