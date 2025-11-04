#!/usr/bin/env python3

import os
import subprocess
import io
import json
import time
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 1. 初始化 ---
app = Flask(__name__)
if not os.path.exists('instance'): os.makedirs('instance')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'monitoring.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')

# --- 2. 新的数据库模型 ---
class MonitorTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(1024), nullable=False)
    cron_schedule = db.Column(db.String(100), nullable=False, default='*/5 * * * *') # 每5分钟
    is_active = db.Column(db.Boolean, default=True)
    screenshot_width = db.Column(db.Integer, default=1920)
    screenshot_max_height = db.Column(db.Integer, default=15000)
    threshold = db.Column(db.Integer, default=500)
    crop_area = db.Column(db.String(200), default='[]') # e.g., '[100, 200, 800, 600]'
    last_checked = db.Column(db.DateTime)
    last_changed = db.Column(db.DateTime)

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

# --- 3. 辅助函数 (基本不变) ---
# ... (get_screenshot, images_are_different, send_email, send_telegram_notification 保持原样) ...
def get_screenshot(driver, url, width, max_height):
    print(f"[{url}] 正在以 {width}px 宽度访问...")
    driver.get(url)
    total_height = driver.execute_script("return document.body.scrollHeight")
    if total_height > max_height:
        total_height = max_height
    driver.set_window_size(width, total_height if total_height > 0 else 1080)
    time.sleep(3)
    png = driver.get_screenshot_as_png()
    return Image.open(io.BytesIO(png))

def images_are_different(img1, img2, threshold):
    diff = ImageChops.difference(img1.convert('RGB'), img2.convert('RGB'))
    if diff.getbbox() is None: return False
    return sum(diff.histogram()) > threshold

def send_email(subject, content, config):
    # ... (此函数代码与上一版相同) ...
    pass

def send_telegram_notification(message, config):
    # ... (此函数代码与上一版相同) ...
    pass

# --- 4. 核心监控与调度逻辑 (全新) ---
def execute_target_check(target_id):
    """为单个目标执行监控检查，由调度器调用"""
    with app.app_context():
        target = MonitorTarget.query.get(target_id)
        notifications_config = NotificationSettings.query.first()
        if not target:
            print(f"[!] 任务触发，但找不到 ID 为 {target_id} 的目标。")
            return

        print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检查: {target.url} ---")
        
        chrome_options = Options()
        # ... (chrome_options 的设置与之前相同) ...
        driver = webdriver.Chrome(options=chrome_options)
        
        try:
            current_img = get_screenshot(driver, target.url, target.screenshot_width, target.screenshot_max_height)
            file_name = f"target_{target.id}.png"
            screenshot_path = os.path.join("/app/screenshots", file_name)
            
            if os.path.exists(screenshot_path):
                last_img = Image.open(screenshot_path)
                img_to_compare_current, img_to_compare_last = current_img, last_img
                
                try:
                    crop_box = json.loads(target.crop_area)
                    if isinstance(crop_box, list) and len(crop_box) == 4:
                        img_to_compare_current = current_img.crop(tuple(crop_box))
                        img_to_compare_last = last_img.crop(tuple(crop_box))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass # 如果格式不正确，则对比完整图片

                if images_are_different(img_to_compare_last, img_to_compare_current, target.threshold):
                    print(f"[!] 检测到变化: {target.url}")
                    target.last_changed = datetime.now()
                    # 发送通知...
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
        scheduler.remove_all_jobs()
        active_targets = MonitorTarget.query.filter_by(is_active=True).all()
        for target in active_targets:
            try:
                scheduler.add_job(
                    id=f'target_{target.id}',
                    func=execute_target_check,
                    args=[target.id],
                    trigger=CronTrigger.from_crontab(target.cron_schedule)
                )
                print(f"[*] 已添加任务: {target.url} (ID: {target.id}), 调度: '{target.cron_schedule}'")
            except Exception as e:
                print(f"[!!!] 添加任务失败 for {target.url}: {e}")
        if not scheduler.running:
            scheduler.start()

# --- 5. Web 路由 (全新) ---
@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    targets = MonitorTarget.query.all()
    notifications = NotificationSettings.query.first()
    return render_template('dashboard.html', targets=targets, notifications=notifications)

@app.route('/target/add', methods=['POST'])
def add_target():
    if 'user_id' not in session: return redirect(url_for('login'))
    # ... 从 request.form 获取数据 ...
    new_target = MonitorTarget(url=request.form['url'], cron_schedule=request.form['cron_schedule'], ...)
    db.session.add(new_target)
    db.session.commit()
    sync_scheduler_from_db() # 重新同步调度器
    flash('监控目标已成功添加！', 'success')
    return redirect(url_for('dashboard'))

@app.route('/target/edit/<int:target_id>', methods=['POST'])
def edit_target(target_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    target = MonitorTarget.query.get_or_404(target_id)
    # ... 从 request.form 更新 target 的属性 ...
    target.url = request.form['url']
    target.cron_schedule = request.form['cron_schedule']
    # ...
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

# 其他路由如 /target/toggle_active/<id>, /settings/notifications 等
# ... (登录、登出、init-db 等保持不变) ...

# --- 6. 启动与初始化 ---
@app.cli.command("init-db")
def init_db():
    db.create_all()
    # ... 创建管理员用户 ...
    if not NotificationSettings.query.first():
        db.session.add(NotificationSettings())
    db.session.commit()
    print("数据库初始化完成。")

with app.app_context():
    db.create_all()
    sync_scheduler_from_db()
