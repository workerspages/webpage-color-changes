# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装所有必需的系统依赖和工具
RUN apt-get update && \
    apt-get install -y \
    msmtp \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    curl \
    unzip \
    wget \
    jq \
    --no-install-recommends

# 2. 从官方 API 获取并安装最新的 Stable 版 Chrome 和 ChromeDriver
RUN \
    # a. 获取最新的 Stable 版 Chrome 和 ChromeDriver for linux64 的下载 URL
    JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" && \
    CHROME_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chrome[] | select(.platform=="linux64") | .url') && \
    DRIVER_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chromedriver[] | select(.platform=="linux64") | .url') && \
    \
    echo "Chrome Download URL: ${CHROME_URL}" && \
    echo "ChromeDriver Download URL: ${DRIVER_URL}" && \
    \
    # b. 下载 Chrome .deb 包和 ChromeDriver .zip 文件
    wget -q -O /tmp/chrome.deb "${CHROME_URL}" && \
    wget -q -O /tmp/chromedriver.zip "${DRIVER_URL}" && \
    \
    # ======================================================================== #
    # == 关键修正：在安装本地 .deb 包之前，必须先更新 apt 包列表 == #
    # ======================================================================== #
    apt-get update && \
    \
    # c. 使用 apt 安装 .deb 包，它现在可以正确地找到并安装所有依赖
    apt-get install -y /tmp/chrome.deb && \
    \
    # d. 解压并安装 ChromeDriver
    unzip -q /tmp/chromedriver.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    \
    # e. 清理工作
    apt-get purge -y --auto-remove wget unzip curl jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# 3. 验证安装
RUN echo "Chrome Version: $(google-chrome --version)" && \
    echo "ChromeDriver Version: $(chromedriver --version)"

# 4. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 拷贝应用代码和启动脚本
COPY monitor.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 6. 定义容器启动命令
ENTRYPOINT ["/app/entrypoint.sh"]
