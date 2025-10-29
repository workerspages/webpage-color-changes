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

# 2. 【经典可靠方案】使用 dpkg + apt-get -f install 来安装 Chrome
RUN \
    # a. 从 API 获取最新的 Stable 版 Chrome 和 ChromeDriver 的下载 URL
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
    # ========================================================================================= #
    # == 关键修正：使用经典的 dpkg + apt-get fix-broken install 方法来处理复杂的依赖关系 == #
    # ========================================================================================= #
    # c. 更新包列表，为解决依赖做准备
    apt-get update && \
    \
    # d. 尝试安装 .deb 包。这步很可能会失败并报错，但这是预期的。`|| true` 确保即使失败，构建也不会停止。
    dpkg -i /tmp/chrome.deb || true && \
    \
    # e. 运行 "fix-broken install"，apt 会自动安装所有 chrome 所需的依赖项
    apt-get install -f -y && \
    \
    # f. 解压并安装 ChromeDriver
    unzip -q /tmp/chromedriver.zip -d /tmp && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/ && \
    chmod +x /usr/local/bin/chromedriver && \
    \
    # g. 清理工作
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
