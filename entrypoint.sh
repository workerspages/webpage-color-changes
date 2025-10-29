#!/bin/sh

# 设置默认监控间隔为 300 秒 (5分钟)
: "${MONITOR_INTERVAL_SECONDS:=300}"

# --- 根据环境变量动态生成 msmtp 配置文件 ---
# 检查是否提供了必要的 SMTP 环境变量
if [ -n "$SMTP_USER" ] && [ -n "$SMTP_PASSWORD" ] && [ -n "$SMTP_HOST" ]; then
    echo "检测到 SMTP 环境变量，正在生成 /root/.msmtprc 配置文件..."

    # 使用 cat 和 heredoc 创建配置文件
    # 这会将 SMTP_HOST, SMTP_PORT, SMTP_FROM, SMTP_USER, SMTP_PASSWORD 的值写入文件
    cat > /root/.msmtprc <<EOF
# 此文件由 entrypoint.sh 动态生成
defaults
auth on
tls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile ~/.msmtp.log

account default
host ${SMTP_HOST}
port ${SMTP_PORT:-587}
from ${SMTP_FROM:-${SMTP_USER}}
user ${SMTP_USER}
password ${SMTP_PASSWORD}
EOF

    # 设置安全权限，确保只有 root 用户可以读写
    chmod 600 /root/.msmtprc
    echo "msmtp 配置文件创建成功。"
else
    echo "警告：未提供完整的 SMTP 环境变量 (需要 SMTP_HOST, SMTP_USER, SMTP_PASSWORD)，邮件通知功能将不可用。"
fi


# --- 启动监控循环 ---
echo "--- 网页变化监控服务启动 ---"
echo "监控间隔设置为: ${MONITOR_INTERVAL_SECONDS} 秒"

# 无限循环执行监控任务
while true; do
  # 执行 Python 监控脚本
  python3 /app/monitor.py
  
  # 等待指定的时间
  echo "等待 ${MONITOR_INTERVAL_SECONDS} 秒后进行下一轮检查..."
  sleep ${MONITOR_INTERVAL_SECONDS}
done
