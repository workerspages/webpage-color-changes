# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装系统依赖：字体、邮件工具、Chrome 和 ChromeDriver
RUN apt-get update && \
    apt-get install -y \
    msmtp \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    wget \
    unzip \
    --no-install-recommends && \
    # 安装 Chrome 和对应的 ChromeDriver (使用新的官方源，更稳定)
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable --no-install-recommends && \
    CHROME_VERSION=$(google-chrome --product-version) && \
    echo "Installed Chrome Version: $CHROME_VERSION" && \
    # 从新的 JSON API 获取匹配的 ChromeDriver
    CHROME_DRIVER_VERSION=$(wget -qO- https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json | grep -oP '"linux64","url":"\K[^"]+' | head -n 1 | sed -e 's|https://storage.googleapis.com/chrome-for-testing-public/||' -e 's|/linux64/chromedriver-linux64.zip||') && \
    echo "Fetching ChromeDriver Version: $CHROME_DRIVER_VERSION" && \
    wget -q --continue -P /tmp https://storage.googleapis.com/chrome-for-testing-public/${CHROME_DRIVER_VERSION}/linux64/chromedriver-linux64.zip && \
    unzip /tmp/chromedriver-linux64.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    # 清理
    apt-get purge -y wget unzip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# 2. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 拷贝应用代码和启动脚本
COPY monitor.py .
COPY entrypoint.sh .

# 赋予启动脚本执行权限
RUN chmod +x entrypoint.sh

# 4. 定义容器启动命令
ENTRYPOINT ["/app/entrypoint.sh"]
