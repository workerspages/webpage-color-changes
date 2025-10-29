# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装基础工具
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

# 2. 【关键】安装 Headless Chrome/ChromeDriver 运行所需的全部依赖库
#    这是解决运行时 exit code 127 错误的根本方法
RUN apt-get update && \
    apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    libasound2 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    --no-install-recommends

# 3. 使用 dpkg + apt-get -f install 的经典方法来安装 Chrome
RUN \
    JSON_URL="https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" && \
    CHROME_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chrome[] | select(.platform=="linux64") | .url') && \
    DRIVER_URL=$(curl -sS ${JSON_URL} | jq -r '.channels.Stable.downloads.chromedriver[] | select(.platform=="linux64") | .url') && \
    wget -q -O /tmp/chrome.deb "${CHROME_URL}" && \
    wget -q -O /tmp/chromedriver.zip "${DRIVER_URL}" && \
    dpkg -i /tmp/chrome.deb || true && \
    apt-get install -f -y && \
    unzip -q /tmp/chromedriver.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    apt-get purge -y --auto-remove wget unzip curl jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# 4. 验证安装
RUN echo "Chrome Version: $(google-chrome --version)" && \
    echo "ChromeDriver Version: $(chromedriver --version)"

# 5. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. 拷贝应用代码和启动脚本
COPY monitor.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# 7. 定义容器启动命令
ENTRYPOINT ["/app/entrypoint.sh"]
