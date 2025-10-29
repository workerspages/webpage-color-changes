# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装系统依赖和工具
#    我们在这里一次性安装好所有需要的工具，包括 curl, gnupg, jq 等
RUN apt-get update && \
    apt-get install -y \
    msmtp \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    curl \
    gnupg \
    unzip \
    wget \
    # jq 是一个强大的命令行 JSON 解析器，是本次修正的关键
    jq \
    --no-install-recommends

# 2. 安装 Google Chrome 浏览器 (这部分是可靠的)
RUN curl -sS https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable --no-install-recommends

# 3. 【全新可靠方法】下载并安装与 Chrome 精确匹配的 ChromeDriver
RUN apt-get update && \
    # a. 获取已安装的 Chrome 的确切版本号
    CHROME_VERSION=$(google-chrome --product-version) && \
    echo "Installed Chrome Version: $CHROME_VERSION" && \
    # b. 使用 jq 从官方 JSON API 中安全、准确地提取下载 URL
    DRIVER_URL=$(curl -sS https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json | jq -r ".versions[] | select(.version == \"$CHROME_VERSION\") | .downloads.chromedriver[] | select(.platform == \"linux64\") | .url") && \
    echo "Fetching ChromeDriver from: $DRIVER_URL" && \
    # c. 下载、解压并移动到系统路径
    wget -q --continue -P /tmp "$DRIVER_URL" && \
    unzip -q /tmp/chromedriver-linux64.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    # d. 赋予执行权限
    chmod +x /usr/local/bin/chromedriver && \
    # e. 清理工作
    apt-get purge -y --auto-remove wget unzip && \
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
