# 推送到 GitHub 指南

## 方法 1：使用 HTTPS（推荐）

### 步骤 1：在 GitHub 上创建仓库

1. 访问 https://github.com/new
2. Repository name: `IP-TRACK`
3. Description: `IP Address to Switch Port Tracking System`
4. 选择 Public 或 Private
5. **不要**勾选 "Initialize this repository with a README"
6. 点击 "Create repository"

### 步骤 2：推送代码

在服务器上运行以下命令（替换 YOUR_USERNAME 为你的 GitHub 用户名）：

```bash
cd /opt/ip-track

# 添加远程仓库
git remote add origin https://github.com/YOUR_USERNAME/IP-TRACK.git

# 推送代码
git push -u origin main
```

系统会提示输入 GitHub 用户名和密码（或 Personal Access Token）。

### 步骤 3：创建 Personal Access Token（如果需要）

如果推送时提示需要 token：

1. 访问 https://github.com/settings/tokens
2. 点击 "Generate new token" → "Generate new token (classic)"
3. Note: `IP-TRACK deployment`
4. 勾选 `repo` 权限
5. 点击 "Generate token"
6. 复制生成的 token（只显示一次！）
7. 推送时使用 token 作为密码

## 方法 2：使用 SSH

### 步骤 1：生成 SSH 密钥（如果还没有）

```bash
ssh-keygen -t ed25519 -C "your_email@example.com"
cat ~/.ssh/id_ed25519.pub
```

### 步骤 2：添加 SSH 密钥到 GitHub

1. 复制上面命令输出的公钥
2. 访问 https://github.com/settings/keys
3. 点击 "New SSH key"
4. 粘贴公钥并保存

### 步骤 3：推送代码

```bash
cd /opt/ip-track

# 添加远程仓库（SSH）
git remote add origin git@github.com:YOUR_USERNAME/IP-TRACK.git

# 推送代码
git push -u origin main
```

## 验证推送成功

推送成功后，访问：
https://github.com/YOUR_USERNAME/IP-TRACK

应该能看到所有代码文件。

## 后续更新代码

以后更新代码时，只需：

```bash
cd /opt/ip-track
git add -A
git commit -m "Update: 描述你的更改"
git push
```
