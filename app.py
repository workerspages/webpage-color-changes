#!/usr/bin/env python3

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
import requests

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 1. 初始化应用、数据库和调度器 ---
app = Flask(__name__)

if not os.path.exists('instance'):
    os.makedirs('instance')

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key_for_flask_session')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'settings.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True)

# --- 2. 数据库模型 (保持不变) ---
class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    monitor_urls = db.Column(db.Text, default='https://www.apple.com.cn,https://www.tesla.cn/')
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
    threshold = db.Column(db.Integer, default=500)
    crop_areas = db.Column(db.Text, default='{}')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


# --- 3. 辅助函数 (保持不变) ---
# ... (get_screenshot, images_are_different, send_email, send_telegram_notification 函数保持原样) ...
def get_screenshot(driver, url, width, max_height):
    print(f"正在以 {width}px 目标宽度访问 {url}...")
    driver.get(url)
    total_height = driver.execute_script("return document.body.scrollHeight")
    if total_height > max_height:
        print(f"警告：页面高度 {total_height}px 超过最大值 {max_height}px，将进行截断。")
        total_height = max_height
    driver.set_window_size(width, total_height if total_height > 0 else 1080)
    time.sleep(2)
    png = driver.get_screenshot_as_png()
    return Image.open(io.BytesIO(png))

def images_are_different(img1, img2, threshold):
    diff = ImageChops.difference(img1.convert('RGB'), img2.convert('RGB'))
    if diff.getbbox() is None: return False
    return sum(diff.histogram()) > threshold

def send_email(subject, content, config):
    if not all([config.to_email, config.smtp_host, config.smtp_user, config.smtp_password]):
        print("邮件配置不完整，跳过发送。")
        return
    msmtp_config = f"""
defaults
auth on
tls on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile ~/.msmtp.log
account default
host {config.smtp_host}
port {config.smtp_port}
from {config.smtp_from or config.smtp_user}
user {config.smtp_user}
password {config.smtp_password}
"""
    config_path = '/tmp/msmtprc_temp'
    with open(config_path, 'w') as f: f.write(msmtp_config)
    email_text = f"Subject: {subject}\n\n{content}"
    try:
        process = subprocess.Popen(['msmtp', '-C', config_path, config.to_email], stdin=subprocess.PIPE)
        process.communicate(email_text.encode('utf-8'))
        print(f"邮件已发送至 {config.to_email}。")
    except Exception as e: print(f"发送邮件时发生错误: {e}")
    finally: os.remove(config_path)

def send_telegram_notification(message, config):
    if not config.telegram_bot_token or not config.telegram_chat_id:
        print("Telegram 配置不完整，跳过发送。")
        return
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    payload = {'chat_id': config.telegram_chat_id, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200: print("Telegram 通知发送成功。")
        else: print(f"发送 Telegram 通知失败: {response.status_code} - {response.text}")
    except Exception as e: print(f"发送 Telegram 通知时发生异常: {e}")

# --- 4. 核心监控逻辑 (保持不变) ---
# ... (run_monitoring_check 函数保持原样) ...
def run_monitoring_check():
    with app.app_context():
        print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始执行监控检查 ---")
        config = Settings.query.first()
        if not config or not config.monitor_urls:
            print("警告：数据库中未配置监控 URL，跳过本轮检查。")
            return
        urls = [url.strip() for url in config.monitor_urls.split(',') if url.strip()]
        try: crop_areas = json.loads(config.crop_areas)
        except json.JSONDecodeError: crop_areas = {}
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'--window-size={config.screenshot_width},1080')
        driver = webdriver.Chrome(options=chrome_options)
        SCREENSHOT_DIR = "/app/screenshots"
        if not os.path.exists(SCREENSHOT_DIR): os.makedirs(SCREENSHOT_DIR)
        try:
            for url in urls:
                print(f"--- 正在检查: {url} ---")
                try:
                    current_img = get_screenshot(driver, url, config.screenshot_width, config.screenshot_max_height)
                    file_name = url.replace("https://", "").replace("http://", "").replace("/", "_") + ".png"
                    screenshot_path = os.path.join(SCREENSHOT_DIR, file_name)
                    if os.path.exists(screenshot_path):
                        last_img = Image.open(screenshot_path)
                        img_to_compare_current, img_to_compare_last = current_img, last_img
                        if url in crop_areas:
                            try:
                                crop_box = tuple(crop_areas[url])
                                img_to_compare_current = current_img.crop(crop_box)
                                img_to_compare_last = last_img.crop(crop_box)
                            except Exception as e: print(f"裁剪图片时出错: {e}。将对比完整图片。")
                        if images_are_different(img_to_compare_last, img_to_compare_current, config.threshold):
                            subject = f"[网页变化提醒] {url} 页面发生变化"
                            content = f"网址 {url} 的页面检测到变化。"
                            tg_message = f"<b>网页变化提醒</b>\n\n检测到页面有新变化！\n<b>网址:</b> {url}"
                            send_email(subject, content, config)
                            send_telegram_notification(tg_message, config)
                        else: print("页面无显著变化。")
                    else: print("首次截图，保存为基准快照。")
                    current_img.save(screenshot_path)
                except Exception as e:
                    print(f"处理 {url} 时发生严重异常: {e}")
                    error_message = f"<b>监控脚本异常</b>\n\n处理网址 {url} 时发生错误:\n<pre>{e}</pre>"
                    send_telegram_notification(error_message, config)
        finally:
            driver.quit()
        print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 本轮检查完成 ---")


# --- 5. Web 路由和视图 (login, logout 保持不变) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_form = request.form['username']
        password_form = request.form['password']
        admin_username_env = os.environ.get('ADMIN_USER', 'admin')
        if username_form == admin_username_env:
            user = User.query.filter_by(username=admin_username_env).first()
            if user and check_password_hash(user.password_hash, password_form):
                session['user_id'] = user.id
                session['username'] = user.username
                return redirect(url_for('settings_page'))
        flash('无效的用户名或密码', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- 【关键修改】更新 settings_page 函数以处理所有表单字段 ---
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
        # --- 从表单更新所有配置项 ---
        # 基础配置
        config.monitor_urls = request.form.get('monitor_urls', '')
        config.monitor_interval_seconds = int(request.form.get('monitor_interval_seconds', 300))
        
        # Telegram 配置
        config.telegram_bot_token = request.form.get('telegram_bot_token', '')
        config.telegram_chat_id = request.form.get('telegram_chat_id', '')

        # SMTP 邮件配置
        config.smtp_host = request.form.get('smtp_host', '')
        config.smtp_port = int(request.form.get('smtp_port', 587))
        config.smtp_user = request.form.get('smtp_user', '')
        # 只有在用户输入新密码时才更新，否则保持旧密码
        if request.form.get('smtp_password'):
            config.smtp_password = request.form.get('smtp_password')
        config.smtp_from = request.form.get('smtp_from', '')
        config.to_email = request.form.get('to_email', '')

        # 高级配置
        config.screenshot_width = int(request.form.get('screenshot_width', 1920))
        config.screenshot_max_height = int(request.form.get('screenshot_max_height', 15000))
        config.threshold = int(request.form.get('threshold', 500))
        config.crop_areas = request.form.get('crop_areas', '{}')
        
        db.session.commit()
        flash('设置已成功保存！后台任务将按新间隔重启。', 'success')
        
        # 使用新的间隔时间重新调度任务
        new_interval = config.monitor_interval_seconds
        if new_interval > 0 and scheduler.get_job('monitoring_job'):
            scheduler.reschedule_job('monitoring_job', trigger='interval', seconds=new_interval)
        
        return redirect(url_for('settings_page'))

    return render_template('settings.html', config=config)


# --- 6. Flask CLI 命令 (保持不变) ---
# ... (init-db 命令保持原样) ...
@app.cli.command("init-db")
def init_db():
    db.create_all()
    admin_user_env = os.environ.get('ADMIN_USER', 'admin')
    admin_pass_env = os.environ.get('ADMIN_PASSWORD', 'admin')
    user = User.query.filter_by(username=admin_user_env).first()
    hashed_password = generate_password_hash(admin_pass_env, method='pbkdf2:sha256')
    if not user:
        print(f"创建管理员用户 '{admin_user_env}'...")
        new_user = User(username=admin_user_env, password_hash=hashed_password)
        db.session.add(new_user)
    else:
        print(f"管理员用户 '{admin_user_env}' 已存在，更新其密码...")
        user.password_hash = hashed_password
    if not Settings.query.first():
        print("创建默认设置记录...")
        db.session.add(Settings())
    db.session.commit()
    print("数据库初始化完成。")

# --- 7. 启动后台调度器 (保持不变) ---
with app.app_context():
    db.create_all()
    config = Settings.query.first()
    if not config:
        config = Settings()
        db.session.add(config)
        db.session.commit()
    interval = config.monitor_interval_seconds if config.monitor_interval_seconds > 0 else 300
    if not scheduler.running:
        scheduler.add_job(
            id='monitoring_job', 
            func=run_monitoring_check, 
            trigger='interval', 
            seconds=interval,
            next_run_time=datetime.now()
        )
        scheduler.start()
        print(f"后台监控任务已启动，检查间隔: {interval} 秒。")
