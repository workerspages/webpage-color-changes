# --- STAGE 1: Build Environment ---
# 使用一个包含完整构建工具的基础镜像
FROM python:3.10-slim-bookworm as builder

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装基础工具和 Chrome 运行所需的全部依赖库
RUN apt-get update && \
    apt-get install -y \
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
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/*

# 3. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. 拷贝应用代码
COPY . .


# --- STAGE 2: Final Production Image ---
# 使用一个干净的、轻量级的 Python 镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 从 builder 阶段拷贝所有必要的系统库
COPY --from=builder /lib/x86_64-linux-gnu/ /lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/ /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/share/fonts/ /usr/share/fonts/
COPY --from=builder /etc/fonts/ /etc/fonts/

# 从 builder 阶段拷贝 Chrome, ChromeDriver 和 Python 虚拟环境
COPY --from=builder /opt/google/chrome/ /opt/google/chrome/
COPY --from=builder /usr/local/bin/chromedriver /usr/local/bin/chromedriver
COPY --from=builder /usr/local/bin/google-chrome /usr/local/bin/google-chrome
COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/

# 从 builder 阶段拷贝应用代码
COPY --from=builder /app /app

# 设置 PATH 环境变量以找到 google-chrome
ENV PATH="/opt/google/chrome:${PATH}"

# 暴露 Gunicorn 运行的端口
EXPOSE 5000

# 容器启动时执行的命令
ENTRYPOINT ["/app/entrypoint.sh"]
