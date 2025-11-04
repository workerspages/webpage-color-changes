# app.py
import os
import subprocess
import sys
import io
import json
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 1. 初始化应用和数据库 ---
app = Flask(__name__)
# 确保 instance 文件夹存在
if not os.path.exists('instance'):
    os.makedirs('instance')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_secure_random_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance/settings.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True)

# --- 2. 数据库模型 ---
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monitor_urls = db.Column(db.Text, default='')
    monitor_interval_seconds = db.Column(db.Integer, default=300)
    telegram_bot_token = db.Column(db.String(200), default='')
    telegram_chat_id = db.Column(db.String(200), default='')
    smtp_host = db.Column(db.String(200), default='')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(200), default='')
    smtp_password = db.Column(db.String(200), default='')
    smtp_from = db.Column(db.String(200), default='')
    to_email = db.Column(db.String(200), default='')
    screenshot_width = db.Column(db.Integer, default=1920)
    screenshot_max_height = db.Column(db.Integer, default=15000)
    threshold = db.Column(db.Integer, default=50)
    crop_areas = db.Column(db.Text, default='{}')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

# --- 3. 核心监控逻辑 (从 monitor.py 移植并修改) ---
def run_monitoring_check():
    """
    这是从原 monitor.py 迁移过来的核心函数。
    它现在从数据库读取配置，而不是环境变量。
    """
    with app.app_context():
        print(f"--- [{datetime.now()}] 开始执行监控检查 ---")
        config = Settings.query.first()
        if not config or not config.monitor_urls:
            print("警告：数据库中未配置监控 URL，跳过本轮检查。")
            return

        urls = [url.strip() for url in config.monitor_urls.split(',') if url.strip()]
        
        # 此处省略了完整的截图和对比函数 (get_screenshot, images_are_different 等)
        # 它们与原 monitor.py 基本相同，但需要将配置项改为从 config 对象获取
        # 例如: THRESHOLD = config.threshold

        # 示例：
        print(f"监控目标: {urls}")
        # ... 此处应包含完整的 selenium 截图、对比、发邮件、发TG通知的逻辑 ...
        # 注意：所有 os.getenv() 都需要替换为 config.属性 的形式
        # 例如: send_telegram_notification(message, config.telegram_bot_token, config.telegram_chat_id)
    print(f"--- [{datetime.now()}] 本轮检查完成 ---")

# --- 4. Web 路由和视图 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            return redirect(url_for('settings_page'))
        else:
            flash('无效的用户名或密码')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def settings_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    config = Settings.query.first()
    if not config:
        config = Settings()
        db.session.add(config)
        db.session.commit()

    if request.method == 'POST':
        # 从表单更新配置
        config.monitor_urls = request.form.get('monitor_urls')
        config.monitor_interval_seconds = int(request.form.get('monitor_interval_seconds'))
        # ... 更新所有其他字段 ...
        config.smtp_host = request.form.get('smtp_host')
        config.smtp_user = request.form.get('smtp_user')
        # ...
        
        db.session.commit()
        flash('设置已保存！监控将在新的间隔时间后重启。')
        
        # 重新调度任务
        scheduler.remove_job('monitoring_job')
        scheduler.add_job(
            id='monitoring_job', 
            func=run_monitoring_check, 
            trigger='interval', 
            seconds=config.monitor_interval_seconds,
            next_run_time=datetime.now() # 立即执行一次
        )
        return redirect(url_for('settings_page'))

    return render_template('settings.html', config=config)

# --- 5. 应用启动 ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # 如果没有用户，创建一个默认用户
        if not User.query.first():
            hashed_password = generate_password_hash('admin', method='pbkdf2:sha256')
            new_user = User(username='admin', password_hash=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            print("默认用户 admin / admin 已创建")
        
        # 获取监控间隔并启动后台任务
        config = Settings.query.first()
        interval = config.monitor_interval_seconds if config else 300
        scheduler.add_job(id='monitoring_job', func=run_monitoring_check, trigger='interval', seconds=interval)
        scheduler.start()

    # 使用 gunicorn 启动时，不会执行这里的 app.run()
    # 这仅用于本地开发测试
    app.run(host='0.0.0.0', port=5000, debug=True)
