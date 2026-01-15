# 网页视觉变化监控系统 (webpage-color-changes)

[![Docker Image Version](https://img.shields.io/docker/v/yesyunxin/webpage-color-changes?sort=semver)](https://hub.docker.com/r/yesyunxin/webpage-color-changes)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

一个功能强大的网页视觉变化监控工具。通过无头浏览器（Chrome）定时截图，利用感知哈希算法（Perceptual Hashing）对比网页变化，并通过 Web 界面进行管理和查看。支持区域裁剪、登录态监控以及多种报警推送方式。

## ✨ 主要功能

*   **Web 管理面板**：直观的 Dashboard，用于添加、编辑、删除和查看监控任务。
*   **精准视觉对比**：使用 `ImageHash` 算法计算汉明距离，有效忽略微小的渲染噪点，只在发生实质性变化时报警。
*   **指定区域监控**：支持通过 Web 界面在快照上直接框选监控区域，忽略页面其他无关部分的变动（如广告、时间显示）。
*   **灵活的调度策略**：支持 **Interval**（每隔 X 分钟/小时/天）和 **Cron 表达式** 两种调度方式。
*   **复杂场景支持**：
    *   **Cookie 登录**：支持注入 JSON 格式的 Cookie 以维持登录态。
    *   **账号密码登录**：支持配置 CSS 选择器自动填写表单并登录。
    *   **中文支持**：内置文泉驿微米黑字体，完美渲染中文网页。
*   **多渠道通知**：
    *   📧 Email (SMTP)
    *   ✈️ Telegram Bot
    *   🐶 Bark (iOS)
    *   ➕ PushPlus (微信)

## 🚀 快速开始 (Docker Compose)

这是最推荐的部署方式。确保你的机器上安装了 Docker 和 Docker Compose。

### 1. 创建 `docker-compose.yml`

将以下内容保存为 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  webpage-color-changes:
    image: yesyunxin/webpage-color-changes:mariadb
    container_name: webpage-color-changes
    restart: unless-stopped
    ports:
      - "8080:5000"
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ./screenshots_data:/app/screenshots
      - ./instance_data:/app/instance
    environment:
      - TZ=Asia/Shanghai
      - ADMIN_USER=admin
      - ADMIN_PASSWORD=admin123
      # (可选) 为 Flask session 设置一个更安全的密钥
      - SECRET_KEY=your_super_secret_key_here
      # --- ↓↓↓ 数据库配置（可选）↓↓↓ ---
      # 不设置 DATABASE_URL 则使用 SQLite（默认）
      # 连接外部 MariaDB 示例:
      # - DATABASE_URL=mysql+pymysql://username:password@host:3306/webpage_color_changes
```

### 2. 启动服务

```bash
docker-compose up -d
```

### 3. 访问系统

打开浏览器访问 `http://localhost:8080` (或你的服务器 IP:8080)。
*   **默认用户名**: `admin`
*   **默认密码**: `admin` (或者你在 docker-compose 中设置的密码)

## 🛠️ 使用指南

### 1. 添加监控目标
在仪表盘点击 **"添加新目标"**：
*   **监控网址**: 必须是以 `http://` 或 `https://` 开头的完整 URL。
*   **调度方式**: 默认每 5 分钟检查一次。也可以使用 Cron 表达式（如 `0 8 * * *` 每天早上 8 点）。
*   **视觉差异阈值**: 默认为 5。数值越小越敏感，0 表示必须完全一致。建议 5-10。

### 2. 区域裁剪 (Crop)
如果你只想监控网页中的某一块（例如价格数字、库存状态）：
1.  先添加目标并让其运行一次（或手动点击“执行”），确保生成了第一张快照。
2.  点击 **"编辑"** 按钮。
3.  在“指定区域”一栏，点击 **"选取区域"** 按钮。
4.  在弹出的模态框中，在图片上拖拽鼠标框选你关注的区域，点击确认。

### 3. 配置通知
点击仪表盘右上角的 **"通知设置"**：
*   **Telegram**: 填写 Bot Token 和 Chat ID。
*   **邮件**: 配置 SMTP 服务器（如 QQ 邮箱、Gmail）。
*   **Bark**: 填写 iOS Bark App 提供的 URL（例如 `https://api.day.app/YOUR_KEY/`）。
*   **PushPlus**: 填写 Token 以通过微信接收通知。

### 4. 登录态监控 (高级)
如果目标页面需要登录可见：
*   **方法 A (推荐 - Cookie)**: 使用浏览器插件（如 EditThisCookie）导出目标网站的 Cookies 为 JSON 格式，粘贴到配置框中。
*   **方法 B (账号密码)**: 填写用户名、密码，并提供对应输入框和登录按钮的 CSS Selector（例如 `#username`, `#password`, `#login-btn`）。系统会在截图前尝试自动登录。

## 🗃️ 数据库配置

系统同时支持 **SQLite** 和 **MariaDB/MySQL** 两种数据库，通过环境变量 `DATABASE_URL` 切换。

### 使用 SQLite（默认）

不需要任何额外配置，系统默认使用 SQLite 存储在 `/app/instance/monitoring.db`。

### 使用外部 MariaDB/MySQL

1. **在 MariaDB 中创建数据库和用户**：

```sql
CREATE DATABASE webpage_monitor CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'monitor_user'@'%' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON webpage_monitor.* TO 'monitor_user'@'%';
FLUSH PRIVILEGES;
```

2. **配置环境变量**：

在 `docker-compose.yml` 中添加 `DATABASE_URL`：

```yaml
environment:
  - DATABASE_URL=mysql+pymysql://monitor_user:your_password@192.168.1.100:3306/webpage-color-changes
```

连接字符串格式：`mysql+pymysql://用户名:密码@主机:端口/数据库名`

## 📁 目录结构说明

挂载的 Volume 对应容器内路径：

*   `/app/instance`: 存放 `monitoring.db` (SQLite 数据库)，保存任务配置和用户数据。
*   `/app/screenshots`: 存放网页截图文件。

## 🔧 开发与构建

如果你想自己构建镜像或进行二次开发：

```bash
# 1. 克隆仓库
git clone https://github.com/workerspages/webpage-color-changes.git
cd webpage-color-changes

# 2. 构建 Docker 镜像
docker build -t my-web-monitor .

# 3. 运行
docker run -d -p 5000:5000 my-web-monitor
```

### 本地开发 (无 Docker)

需要 Python 3.10+ 和 Chrome 浏览器。

1.  安装依赖: `pip install -r requirements.txt`
2.  确保 `chromedriver` 在系统 PATH 中。
3.  初始化数据库: `flask init-db`
4.  运行: `python app.py`

## ⚠️ 注意事项

1.  **内存占用**: Chrome 比较吃内存，建议服务器至少有 1GB RAM，或限制并发任务数。
2.  **反爬虫**: 频繁抓取某些网站可能会触发反爬机制。建议合理设置抓取间隔。
3.  **安全**: 不要在公共网络环境下使用默认密码。请修改 `ADMIN_PASSWORD`。

## 📄 License

MIT License
