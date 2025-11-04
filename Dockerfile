# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装基础工具和 Chrome 运行所需的全部依赖库
RUN apt-get update && \
    apt-get install -y \
    msmtp \
    curl unzip wget jq \
    libglib2.0-0 libnss3 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libgdk-pixbuf2.0-0 libgtk-3-0 libasound2 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 fonts-wqy-zenhei fonts-wqy-microhei \
    --no-install-recommends

# 2. 动态获取最新稳定版的 Chrome 和 ChromeDriver 并安装
RUN \
    JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" && \
    CHROME_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chrome[] | select(.platform=="linux64") | .url') && \
    DRIVER_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chromedriver[] | select(.platform=="linux64") | .url') && \
    wget -q -O /tmp/chrome.deb "${CHROME_URL}" && \
    wget -q -O /tmp/chromedriver.zip "${DRIVER_URL}" && \
    dpkg -i /tmp/chrome.deb || apt-get install -f -y && \
    unzip -q /tmp/chromedriver.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver

# 3. 验证安装 (可选，但有助于调试)
RUN echo "Chrome path: $(which google-chrome)" && \
    echo "ChromeDriver version: $(chromedriver --version)"

# 4. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 拷贝所有应用代码
COPY . .

# 6. 清理不必要的文件以减小镜像大小
RUN apt-get purge -y --auto-remove wget unzip curl jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# 7. 暴露 Gunicorn 运行的端口
EXPOSE 5000

# 8. 容器启动时执行的命令
ENTRYPOINT ["/app/entrypoint.sh"]
