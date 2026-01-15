#!/bin/sh

# 设置脚本在遇到错误时立即退出
set -e

# 切换到应用的工作目录
cd /app

# 1. 调用在 app.py 中定义的 'init-db' 命令
#    这个命令会创建数据库表，并根据环境变量创建或更新管理员账户。
#    这是比使用 'flask shell' 更稳定、更推荐的方式。
echo "--- 正在初始化数据库和管理员账户 ---"
flask init-db

# 2. 启动 Gunicorn Web 服务器
#    'exec' 命令会用 gunicorn 进程替换当前的 shell 进程，
#    这是容器启动命令的最佳实践，有助于正确处理信号（如 docker stop）。
echo "--- 启动 Gunicorn Web 服务器，监听端口 5000 ---"

# ${PORT:-5000} 的意思是：
# 如果系统有环境变量 PORT (比如在 BTP 上)，就用那个；
# 如果没有 (比如在你本地电脑)，就默认用 5000。
exec gunicorn --workers 2 --threads 4 --bind 0.0.0.0:${PORT:-5000} app:app
