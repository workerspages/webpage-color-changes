# 使用一个轻量级的 Python 基础镜像
FROM python:3.10-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 apt-get 交互式提问
ENV DEBIAN_FRONTEND=noninteractive

# 1. 安装系统依赖：邮件工具、字体和必要的软件包
#    我们将 Chrome 和 ChromeDriver 的安装分开，使其更清晰
RUN apt-get update && \
    apt-get install -y \
    msmtp \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    curl \
    gnupg \
    --no-install-recommends

# 2. 【全新方法】安装 Google Chrome 和匹配的 ChromeDriver
#    使用 Google 官方的 Chrome for Testing 仓库，这是最稳定可靠的方式
RUN curl -sS https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y \
    google-chrome-stable \
    # 注意：现在可以通过包管理器直接安装 ChromeDriver！
    chromedriver \
    --no-install-recommends && \
    # 清理工作
    rm -rf /var/lib/apt/lists/*

# 3. 验证安装
RUN echo "Chrome Version: $(google-chrome --version)" && \
    echo "ChromeDriver Version: $(chromedriver --version)"

# 4. 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. 拷贝应用代码和启动脚本
COPY monitor.py .
COPY entrypoint.sh .

# 赋予启动脚本执行权限
RUN chmod +x entrypoint.sh

# 6. 定义容器启动命令
ENTRYPOINT ["/app/entrypoint.sh"]
