# Dockerfile

# --- Stage 1: 使用官方 Python 镜像作为基础 ---
# 选择一个特定版本的 slim 镜像是最佳实践，既保证了环境一致性，又减小了体积。
FROM python:3.10-slim-bookworm

# --- 设置环境变量 ---
# 防止 apt-get 在构建过程中进行交互式提问
ENV DEBIAN_FRONTEND=noninteractive
# 确保 Python 输出日志时不会被缓冲，便于在 Docker logs 中实时查看
ENV PYTHONUNBUFFERED=1

# --- 设置工作目录 ---
WORKDIR /app

# --- 安装系统依赖 ---
# 分为两部分：
# 1. 构建依赖 (build-deps): 这些是安装 Chrome 和 Python 包时需要，但最终运行时不需要的工具。
# 2. 运行时依赖 (runtime-deps): Chrome 和 msmtp 运行所必需的库。
# 注意: curl 被同时视为构建和运行时依赖，因此不会被清理。
RUN apt-get update && \
    apt-get install -y \
    # build-deps & runtime-deps
    curl \
    # build-deps
    wget unzip jq \
    # runtime-deps
    msmtp \
    libglib2.0-0 libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libgdk-pixbuf2.0-0 libgtk-3-0 libasound2 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 \
    # 中文字体支持
    fonts-wqy-zenhei fonts-wqy-microhei \
    --no-install-recommends

# --- 安装 Chrome 浏览器 和 ChromeDriver ---
# 使用 Google 官方的 JSON 端点来动态获取最新的稳定版，确保浏览器始终是新的。
RUN \
    JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" && \
    CHROME_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chrome[] | select(.platform=="linux64") | .url') && \
    DRIVER_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chromedriver[] | select(.platform=="linux64") | .url') && \
    wget -q -O /tmp/chrome.deb "${CHROME_URL}" && \
    wget -q -O /tmp/chromedriver.zip "${DRIVER_URL}" && \
    # 安装 Chrome，如果缺少依赖则自动修复
    dpkg -i /tmp/chrome.deb || apt-get install -f -y && \
    # 解压并移动 ChromeDriver 到系统路径
    unzip -q /tmp/chromedriver.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver

# --- 安装 Python 依赖 ---
# 首先只复制 requirements.txt 并安装，这样可以利用 Docker 的层缓存。
# 只有当 requirements.txt 变化时，这一层才会重新构建。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 拷贝应用代码 ---
# 将项目中的所有文件拷贝到工作目录
COPY . .

# --- 赋予启动脚本执行权限 ---
RUN chmod +x /app/entrypoint.sh

# --- 【关键修改】清理工作 (保留 curl) ---
# 清理掉不再需要的构建依赖和 apt 缓存，以减小最终镜像的大小。
RUN apt-get purge -y --auto-remove wget unzip jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# --- 暴露端口 ---
# 声明容器将监听的端口，与 gunicorn 启动时绑定的端口一致
EXPOSE 5000

# --- 设置容器启动命令 ---
# 使用 entrypoint.sh 脚本来启动应用
ENTRYPOINT ["/app/entrypoint.sh"]
