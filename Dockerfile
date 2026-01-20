# Dockerfile - 多架构支持 (linux/amd64 + linux/arm64)

# --- Stage 1: 使用官方 Python 镜像作为基础 ---
FROM python:3.10-slim-bookworm

# --- 设置环境变量 ---
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# --- 设置工作目录 ---
WORKDIR /app

# --- 安装系统依赖和 Chromium ---
# 使用 Chromium 替代 Chrome，因为 Chromium 原生支持多架构 (amd64/arm64)
RUN apt-get update && \
    apt-get install -y \
    # 核心依赖
    curl \
    # Chromium 浏览器和驱动 (自动适配当前架构)
    chromium chromium-driver \
    # 邮件发送
    msmtp \
    # 中文字体支持
    fonts-wqy-zenhei fonts-wqy-microhei \
    --no-install-recommends && \
    # 清理 apt 缓存
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- 创建 Chromium 包装脚本 ---
# Selenium 默认查找 chromedriver，但 Debian 安装的是 chromium-driver
# 创建符号链接确保兼容性
RUN ln -sf /usr/bin/chromium /usr/bin/google-chrome && \
    ln -sf /usr/bin/chromedriver /usr/local/bin/chromedriver

# --- 安装 Python 依赖 ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 拷贝应用代码 ---
COPY . .

# --- 赋予启动脚本执行权限 ---
RUN chmod +x /app/entrypoint.sh

# --- 暴露端口 ---
EXPOSE 5000

# --- 设置容器启动命令 ---
ENTRYPOINT ["/app/entrypoint.sh"]
