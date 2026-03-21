# nmap安装指南

## 方法1: 使用修复后的脚本（推荐）

```bash
cd /opt/IP-Track
./install_nmap.sh
```

## 方法2: 手动安装（如果脚本失败）

### 步骤1: 停止服务
```bash
cd /opt/IP-Track
sudo docker compose down
```

### 步骤2: 重新构建backend镜像
```bash
sudo docker compose build backend
```

你会看到类似这样的输出：
```
[+] Building 45.2s (12/12) FINISHED
 => [internal] load build definition from Dockerfile
 => [internal] load .dockerignore
 => [internal] load metadata for docker.io/library/python:3.11-slim
 => [1/7] FROM docker.io/library/python:3.11-slim
 => [2/7] WORKDIR /app
 => [3/7] RUN apt-get update && apt-get install -y iputils-ping arp-scan net-tools nmap
 => [4/7] COPY requirements.txt .
 => [5/7] RUN pip install --no-cache-dir -r requirements.txt
 => [6/7] COPY src/ ./src/
 => [7/7] RUN mkdir -p logs
 => exporting to image
 => => exporting layers
 => => writing image sha256:...
 => => naming to docker.io/library/ip-track-backend
```

**关键**: 你应该看到第3步安装了nmap：
```
=> [3/7] RUN apt-get update && apt-get install -y iputils-ping arp-scan net-tools nmap
```

### 步骤3: 启动服务
```bash
sudo docker compose up -d
```

### 步骤4: 验证nmap安装
```bash
sudo docker exec iptrack-backend nmap --version
```

**成功的输出**：
```
Nmap version 7.93 ( https://nmap.org )
Platform: x86_64-pc-linux-gnu
Compiled with: liblua-5.3.6 openssl-3.0.9 libssh2-1.10.0 libz-1.2.13 libpcre-8.39 libpcap-1.10.3 nmap-libdnet-1.12 ipv6
Compiled without:
Available nsock engines: epoll poll select
```

如果看到版本号，说明安装成功！

### 步骤5: 测试OS检测
```bash
# 进入容器
sudo docker exec -it iptrack-backend bash

# 在容器内测试
nmap -O --osscan-guess 10.71.192.1

# 退出容器
exit
```

## 验证安装

### 检查1: nmap命令可用
```bash
sudo docker exec iptrack-backend which nmap
```

应该返回：`/usr/bin/nmap`

### 检查2: 版本信息
```bash
sudo docker exec iptrack-backend nmap --version
```

应该显示版本号（如7.93或更高）

### 检查3: 运行诊断工具
```bash
sudo docker exec iptrack-backend /app/quick_test.sh
```

应该看到：
```
1. 检查nmap安装状态...
   ✅ nmap已安装: Nmap version 7.93 ( https://nmap.org )
```

## 故障排查

### 问题1: 构建时网络错误
**症状**: `Failed to fetch http://deb.debian.org/...`

**解决**:
```bash
# 检查网络连接
ping -c 3 8.8.8.8

# 如果有代理，修改Dockerfile添加代理
# 或者重试构建
sudo docker compose build --no-cache backend
```

### 问题2: 权限被拒绝
**症状**: `permission denied while trying to connect to the Docker daemon`

**解决**:
```bash
# 方法1: 使用sudo
sudo docker compose build backend

# 方法2: 将用户添加到docker组（推荐）
sudo usermod -aG docker $USER
newgrp docker

# 之后无需sudo
docker compose build backend
```

### 问题3: 容器未启动
**症状**: `Error response from daemon: Container is not running`

**解决**:
```bash
# 检查容器状态
sudo docker ps -a | grep iptrack-backend

# 如果状态是Exited，查看日志
sudo docker logs iptrack-backend

# 重启容器
sudo docker restart iptrack-backend
```

## 测试OS检测功能

安装完成后，测试OS检测：

```bash
# 进入容器
sudo docker exec -it iptrack-backend bash

# 运行Python诊断
python /app/diagnose_ipam.py

# 跳过DNS和子网，按Ctrl+C退出
```

然后在IPAM主页：
1. 选择一个子网
2. 点击"扫描"按钮
3. 等待扫描完成（5-30秒）
4. 进入子网详情页
5. 查看"Machine Type"列

**之前**（没有nmap）：
- OS Name: Windows / Linux / Unknown

**之后**（有nmap）：
- OS Name: Windows 10, Ubuntu 22.04, CentOS 7, macOS 12.0

## 快速命令参考

```bash
# 停止服务
sudo docker compose down

# 构建镜像
sudo docker compose build backend

# 启动服务
sudo docker compose up -d

# 验证nmap
sudo docker exec iptrack-backend nmap --version

# 查看容器日志
sudo docker logs iptrack-backend --tail 50

# 重启容器
sudo docker restart iptrack-backend

# 进入容器
sudo docker exec -it iptrack-backend bash
```

---

**创建日期**: 2026-03-18
