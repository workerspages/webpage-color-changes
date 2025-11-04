#!/usr/bin/env python3

import os
import subprocess
import io
import json
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 1. 初始化应用、数据库和调度器 ---
app = Flask(__name__)

# 确保 instance 和 screenshots 文件夹存在
if not os.path.exists('instance'): os.makedirs('instance')
SCREENSHOT_DIR = "/app/screenshots"
if not os.path.exists(SCREENSHOT_DIR): os.makedirs(SCREENSHOT_DIR)

# 配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_and_secure_key_dev')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'monitoring.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')


# --- 2. 数据库模型 ---
class MonitorTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    url = db.Column(db.String(1024), nullable=False)
    cron_schedule = db.Column(db.String(100), nullable=False, default='*/5 * * * *')
    is_active = db.Column(db.Boolean, default=True)
    screenshot_width = db.Column(db.Integer, default=1920)
    screenshot_max_height = db.Column(db.Integer, default=15000)
    threshold = db.Column(db.Integer, default=500)
    crop_area = db.Column(db.String(200), default='[]')
    last_checked = db.Column(db.DateTime)
    last_changed = db.Column(db.DateTime)

    @property
    def screenshot_filename(self):
        """生成此目标的截图文件名"""
        return f"target_{self.id}.png"

class NotificationSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    telegram_bot_token = db.Column(db.String(200), default='')
    telegram_chat_id = db.Column(db.String(200), default='')
    smtp_host = db.Column(db.String(200), default='')
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(200), default='')
    smtp_password = db.Column(db.String(200), default='')
    smtp_from = db.Column(db.String(200), default='')
    to_email = db.Column(db.String(200), default='')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


# --- 3. 辅助函数 ---
def get_screenshot(driver, url, width, max_height):
    print(f"[{url}] 正在以 {width}px 宽度访问...")
    driver.get(url)
    total_height = driver.execute_script("return document.body.scrollHeight")
    if total_height > max_height: total_height = max_height
    driver.set_window_size(width, total_height if total_height > 0 else 1080)
    time.sleep(3)
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
    config_path = f'/tmp/msmtprc_{int(time.time())}'
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


# --- 4. 核心监控与调度逻辑 ---
def execute_target_check(target_id):
    """为单个目标执行监控检查"""
    with app.app_context():
        target = MonitorTarget.query.get(target_id)
        notifications_config = NotificationSettings.query.first()
        if not target: return

        print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检查: {target.url} ---")
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'--window-size={target.screenshot_width},1080')
        driver = webdriver.Chrome(options=chrome_options)
        try:
            current_img = get_screenshot(driver, target.url, target.screenshot_width, target.screenshot_max_height)
            screenshot_path = os.path.join(SCREENSHOT_DIR, target.screenshot_filename)
            
            if os.path.exists(screenshot_path):
                last_img = Image.open(screenshot_path)
                img_to_compare_current, img_to_compare_last = current_img, last_img
                try:
                    crop_box = json.loads(target.crop_area)
                    if isinstance(crop_box, list) and len(crop_box) == 4:
                        img_to_compare_current = current_img.crop(tuple(crop_box))
                        img_to_compare_last = last_img.crop(tuple(crop_box))
                except (json.JSONDecodeError, TypeError, ValueError): pass

                if images_are_different(img_to_compare_last, img_to_compare_current, target.threshold):
                    print(f"[!!!] 检测到变化: {target.url}")
                    target.last_changed = datetime.now()
                    subject = f"[网页变化] {target.name or target.url}"
                    content = f"监控目标 '{target.name}' ({target.url}) 检测到页面发生视觉变化。"
                    tg_message = f"<b>网页变化提醒</b>\n\n<b>目标:</b> {target.name}\n<b>网址:</b> {target.url}\n\n检测到页面有新变化！"
                    if notifications_config:
                        send_email(subject, content, notifications_config)
                        send_telegram_notification(tg_message, notifications_config)
                else:
                    print(f"[-] 页面无变化: {target.url}")
            else:
                print(f"[*] 首次截图，保存基准: {target.url}")

            current_img.save(screenshot_path)
            target.last_checked = datetime.now()
            db.session.commit()
        except Exception as e:
            print(f"[!!!] 处理 {target.url} 时发生严重异常: {e}")
        finally:
            driver.quit()

def sync_scheduler_from_db():
    """从数据库同步所有监控任务到调度器"""
    with app.app_context():
        if scheduler.running:
            scheduler.remove_all_jobs()
        active_targets = MonitorTarget.query.filter_by(is_active=True).all()
        for target in active_targets:
            try:
                scheduler.add_job(
                    id=f'target_{target.id}', func=execute_target_check, args=[target.id],
                    trigger=CronTrigger.from_crontab(target.cron_schedule, timezone='Asia/Shanghai')
                )
                print(f"[*] 已添加任务: {target.name or target.url} (ID: {target.id}), 调度: '{target.cron_schedule}'")
            except Exception as e:
                print(f"[!!!] 添加任务失败 for {target.url}: {e}")
        if not scheduler.running and active_targets:
            scheduler.start()


# --- 5. Web 路由 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            session['user_id'], session['username'] = user.id, user.username
            return redirect(url_for('dashboard'))
        flash('无效的用户名或密码', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/screenshots/<path:filename>')
def serve_screenshot(filename):
    if 'user_id' not in session: return "Unauthorized", 401
    return send_from_directory(SCREENSHOT_DIR, filename)

@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    targets = MonitorTarget.query.order_by(MonitorTarget.id.desc()).all()
    notifications = NotificationSettings.query.first()
    return render_template('dashboard.html', targets=targets, notifications=notifications, now=datetime.now)

@app.route('/target/add', methods=['POST'])
def add_target():
    if 'user_id' not in session: return redirect(url_for('login'))
    new_target = MonitorTarget(
        name=request.form.get('name'), url=request.form.get('url'),
        cron_schedule=request.form.get('cron_schedule', '*/5 * * * *'),
        screenshot_width=int(request.form.get('screenshot_width', 1920)),
        screenshot_max_height=int(request.form.get('screenshot_max_height', 15000)),
        threshold=int(request.form.get('threshold', 500)),
        crop_area=request.form.get('crop_area', '[]'),
        is_active=request.form.get('is_active') == 'on'
    )
    db.session.add(new_target)
    db.session.commit()
    sync_scheduler_from_db()
    flash('监控目标已成功添加！', 'success')
    return redirect(url_for('dashboard'))

@app.route('/target/edit', methods=['POST'])
def edit_target():
    if 'user_id' not in session: return redirect(url_for('login'))
    target_id = request.form.get('target_id')
    target = MonitorTarget.query.get_or_404(target_id)
    target.name = request.form.get('name')
    target.url = request.form.get('url')
    target.cron_schedule = request.form.get('cron_schedule')
    target.screenshot_width = int(request.form.get('screenshot_width'))
    target.screenshot_max_height = int(request.form.get('screenshot_max_height'))
    target.threshold = int(request.form.get('threshold'))
    target.crop_area = request.form.get('crop_area')
    target.is_active = request.form.get('is_active') == 'on'
    db.session.commit()
    sync_scheduler_from_db()
    flash('监控目标已成功更新！', 'success')
    return redirect(url_for('dashboard'))

@app.route('/target/delete/<int:target_id>', methods=['POST'])
def delete_target(target_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    target = MonitorTarget.query.get_or_404(target_id)
    db.session.delete(target)
    db.session.commit()
    sync_scheduler_from_db()
    flash('监控目标已成功删除！', 'info')
    return redirect(url_for('dashboard'))

@app.route('/target/toggle/<int:target_id>', methods=['POST'])
def toggle_target(target_id):
    if 'user_id' not in session: return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    target = MonitorTarget.query.get_or_404(target_id)
    target.is_active = not target.is_active
    db.session.commit()
    sync_scheduler_from_db()
    return jsonify({'status': 'success', 'is_active': target.is_active})

@app.route('/notifications/save', methods=['POST'])
def save_notifications():
    if 'user_id' not in session: return redirect(url_for('login'))
    settings = NotificationSettings.query.first()
    if not settings: settings = NotificationSettings()
    settings.telegram_bot_token = request.form.get('telegram_bot_token')
    settings.telegram_chat_id = request.form.get('telegram_chat_id')
    settings.smtp_host = request.form.get('smtp_host')
    settings.smtp_port = int(request.form.get('smtp_port', 587))
    settings.smtp_user = request.form.get('smtp_user')
    if request.form.get('smtp_password'):
        settings.smtp_password = request.form.get('smtp_password')
    settings.smtp_from = request.form.get('smtp_from')
    settings.to_email = request.form.get('to_email')
    db.session.add(settings)
    db.session.commit()
    flash('通知设置已成功保存！', 'success')
    return redirect(url_for('dashboard'))


# --- 6. 启动与初始化 ---
@app.cli.command("init-db")
def init_db():
    """初始化数据库并创建管理员"""
    db.create_all()
    admin_user = os.environ.get('ADMIN_USER', 'admin')
    admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin')
    user = User.query.filter_by(username=admin_user).first()
    if not user:
        user = User(username=admin_user)
        db.session.add(user)
    user.password_hash = generate_password_hash(admin_pass, method='pbkdf2:sha256')
    if not NotificationSettings.query.first():
        db.session.add(NotificationSettings())
    db.session.commit()
    print(f"数据库初始化完成。管理员 '{admin_user}' 已配置。")

with app.app_context():
    db.create_all()
    # 确保至少有一个通知设置行存在
    if not NotificationSettings.query.first():
        db.session.add(NotificationSettings())
        db.session.commit()
    # 启动时同步一次调度器
    sync_scheduler_from_db()
