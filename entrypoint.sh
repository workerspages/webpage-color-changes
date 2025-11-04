#!/bin/sh

# 设置工作目录
cd /app

# 初始化数据库和默认用户
echo "正在初始化数据库..."
flask shell <<EOF
from app import db, User
from werkzeug.security import generate_password_hash
db.create_all()
if not User.query.filter_by(username='admin').first():
    hashed_password = generate_password_hash('admin', method='pbkdf2:sha256')
    new_user = User(username='admin', password_hash=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    print("默认管理员 'admin' (密码 'admin') 已创建。请登录后立即修改密码！")
else:
    print("数据库已存在。")
exit()
EOF

# 启动 Gunicorn Web 服务器
echo "启动 Gunicorn Web 服务器..."
exec gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
