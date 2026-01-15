#!/usr/bin/env python3

import os
import io
import json
import time
import traceback 
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from urllib.parse import urlsplit
from threading import BoundedSemaphore

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image, ImageDraw
import imagehash


# --- 1. 初始化应用、数据库和调度器 ---
app = Flask(__name__)

# 确保 instance 和 screenshots 文件夹存在
if not os.path.exists('instance'): os.makedirs('instance')
SCREENSHOT_DIR = "/app/screenshots"
if not os.path.exists(SCREENSHOT_DIR): os.makedirs(SCREENSHOT_DIR)

# 配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_and_secure_key_for_development')

# --- 数据库配置（支持 SQLite 和 MariaDB/MySQL）---
# 优先使用环境变量 DATABASE_URL，未设置则使用 SQLite
database_url = os.environ.get('DATABASE_URL')
if database_url:
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    print(f"[DB] 使用外部数据库: {database_url.split('@')[-1] if '@' in database_url else database_url}")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'monitoring.db')
    print("[DB] 使用本地 SQLite 数据库")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')

# --- [NEW] 并发控制 ---
# 限制同时运行的浏览器实例数量，防止内存耗尽
# 建议值: 1GB内存设为1-2, 2GB+内存可设为3-4
MAX_CONCURRENT_BROWSERS = 2
browser_semaphore = BoundedSemaphore(MAX_CONCURRENT_BROWSERS)


# --- 2. 数据库模型 ---
class MonitorTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    url = db.Column(db.String(1024), nullable=False)
    schedule_type = db.Column(db.String(20), nullable=False, default='interval')
    interval_minutes = db.Column(db.Integer, nullable=True, default=5)
    cron_schedule = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    screenshot_width = db.Column(db.Integer, default=1920)
    screenshot_max_height = db.Column(db.Integer, default=15000)
    threshold = db.Column(db.Integer, default=5)
    crop_area = db.Column(db.String(200), default='[]')
    login_method = db.Column(db.String(50), default='none')
    cookies = db.Column(db.Text, nullable=True)
    login_username = db.Column(db.String(255), nullable=True)
    login_password = db.Column(db.String(255), nullable=True)
    username_selector = db.Column(db.String(255), nullable=True)
    password_selector = db.Column(db.String(255), nullable=True)
    submit_button_selector = db.Column(db.String(255), nullable=True)
    last_checked = db.Column(db.DateTime)
    last_changed = db.Column(db.DateTime)
    @property
    def screenshot_filename(self): return f"target_{self.id}.png"

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
    bark_url = db.Column(db.String(500), default='')
    pushplus_token = db.Column(db.String(200), default='')

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


# --- 3. 辅助函数 ---
# [MODIFIED] 强制设置窗口大小，解决响应式布局问题
def get_screenshot(driver, url, width, max_height):
    print(f"[DEBUG][get_screenshot] 准备截图，URL: {url}")
    
    # 1. 访问页面
    driver.get(url)
    
    # 2. 强制设置窗口大小为用户指定的尺寸
    # 这样可以模拟固定的显示器分辨率 (如 1920x1080)
    # 不再依赖 document.body.scrollHeight，避免动态加载页面的高度计算干扰
    driver.set_window_size(width, max_height)
    
    print(f"[DEBUG] 已强制设置窗口尺寸: {width}x{max_height}")
    
    # 3. 等待页面元素加载和布局稳定
    # YouTube 等动态网站图片加载较慢，Eager模式下必须手动多等一会儿
    # 建议设置为 20 秒，确保图片、字体和布局完全渲染
    print("[DEBUG] 等待页面渲染 (20秒)...")
    time.sleep(20)
    
    # 4. 截图
    png = driver.get_screenshot_as_png()
    print("[DEBUG][get_screenshot] 截图成功。")
    
    return Image.open(io.BytesIO(png))

def images_are_different(img1, img2, hamming_distance_threshold):
    hash1 = imagehash.dhash(img1)
    hash2 = imagehash.dhash(img2)
    distance = hash1 - hash2
    print(f"[DEBUG] 图片1哈希: {hash1}")
    print(f"[DEBUG] 图片2哈希: {hash2}")
    print(f"[DEBUG] 计算出的汉明距离: {distance}")
    return distance > hamming_distance_threshold

# [MODIFIED] 使用 smtplib 替代 msmtp
def send_email(subject, content, config):
    if not all([config.to_email, config.smtp_host, config.smtp_user, config.smtp_password]):
        print("邮件配置不完整，跳过发送。")
        return

    try:
        # 构建邮件对象
        message = MIMEText(content, 'plain', 'utf-8')
        message['From'] = Header(config.smtp_from or config.smtp_user, 'utf-8')
        message['To'] = Header(config.to_email, 'utf-8')
        message['Subject'] = Header(subject, 'utf-8')

        print(f"[Email] 正在连接 SMTP 服务器: {config.smtp_host}:{config.smtp_port}...")
        
        # 根据端口选择连接方式
        if config.smtp_port == 465:
            # SSL 连接
            server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30)
        else:
            # 普通连接 (尝试 STARTTLS)
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30)
            try:
                server.starttls()
            except Exception as e:
                print(f"[Email] STARTTLS 未启用或失败 (可能无需加密): {e}")

        server.login(config.smtp_user, config.smtp_password)
        server.sendmail(config.smtp_from or config.smtp_user, [config.to_email], message.as_string())
        server.quit()
        print(f"[Email] 邮件已成功发送至 {config.to_email}。")
        
    except Exception as e:
        print(f"[Email] 发送邮件时发生错误: {e}")
        traceback.print_exc()

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

def send_bark_notification(title, content, config):
    if not config.bark_url:
        print("Bark URL 未配置，跳过发送。")
        return
    try:
        parts = urlsplit(config.bark_url)
        base_url = f"{parts.scheme}://{parts.netloc}"
        device_key = parts.path.strip('/')
        if not device_key: raise IndexError
    except (IndexError, AttributeError):
        print(f"发送 Bark 通知失败: 无法从 '{config.bark_url}' 中正确解析出服务器地址和设备 Key。请检查格式是否为 http(s)://server/key/")
        return
        
    url = f"{base_url}/push"
    payload = {"title": title, "body": content, "device_key": device_key}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        try:
            response_json = response.json()
            if response.status_code == 200 and response_json.get("code") == 200:
                print("Bark 通知发送成功。")
            else:
                print(f"发送 Bark 通知失败: {response.status_code} - {response.text}")
        except json.JSONDecodeError:
            print(f"发送 Bark 通知失败: 收到非JSON响应 {response.status_code} - {response.text}")
    except Exception as e:
        print(f"发送 Bark 通知时发生异常: {e}")

def send_pushplus_notification(title, content, config):
    if not config.pushplus_token:
        print("PushPlus Token 未配置，跳过发送。")
        return
    url = "http://www.pushplus.plus/send"
    payload = {"token": config.pushplus_token, "title": title, "content": content.replace('\n', '<br>'), "template": "html"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200 and response.json().get("code") == 200:
            print("PushPlus 通知发送成功。")
        else:
            print(f"发送 PushPlus 通知失败: {response.text}")
    except Exception as e: print(f"发送 PushPlus 通知时发生异常: {e}")


# --- 4. 核心监控与调度逻辑 ---
def execute_target_check(target_id):
    # [MODIFIED] 使用信号量进行并发控制
    # blocking=False: 如果当前已有足够多的浏览器在运行，则直接跳过本次检查，防止堆积
    # blocking=True: 会阻塞线程等待，直到有空闲资源
    acquired = browser_semaphore.acquire(blocking=True, timeout=10) 
    if not acquired:
        print(f"[WARN] 系统繁忙，跳过任务 ID: {target_id} (并发限制: {MAX_CONCURRENT_BROWSERS})")
        return

    try:
        print(f"\n[DEBUG] execute_target_check 函数被调用, 目标ID: {target_id}")
        with app.app_context():
            target = MonitorTarget.query.get(target_id)
            notifications_config = NotificationSettings.query.first()
            if not target: 
                print(f"[DEBUG] 目标ID {target_id} 在数据库中未找到，任务终止。")
                return

            print(f"--- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检查: {target.name or target.url} ---")
            driver = None
            try:
                print("[DEBUG] 准备配置 Chrome Options...")
                chrome_options = Options()
                chrome_options.add_argument('--headless')
                chrome_options.add_argument('--disable-gpu')
                chrome_options.add_argument('--no-sandbox')
                chrome_options.add_argument('--disable-dev-shm-usage')
                chrome_options.add_argument(f'--window-size={target.screenshot_width},1080')

                # 【关键修改】设置页面加载策略为 'eager'
                # 解决一直加载转圈导致超时的问题
                chrome_options.page_load_strategy = 'eager'
                print("[DEBUG] Chrome Options 配置完成。")
                
                print("[DEBUG] 正在初始化 webdriver.Chrome...")
                driver = webdriver.Chrome(options=chrome_options)

                driver.set_page_load_timeout(600)
                driver.set_script_timeout(600)
                
                print("[DEBUG] webdriver.Chrome 初始化成功！")
                
                driver.get(target.url)
                print(f"[DEBUG] 已访问初始 URL: {target.url}")
                
                if target.login_method == 'cookie' and target.cookies:
                    try:
                        cookies = json.loads(target.cookies)
                        for cookie in cookies:
                            if 'expiry' in cookie: cookie['expiry'] = int(cookie['expiry'])
                            driver.add_cookie(cookie)
                        print(f"[*] 成功加载 {len(cookies)} 个 Cookies。正在刷新页面...")
                        driver.get(target.url)
                    except Exception as e: print(f"[!!!] 加载 Cookies 失败: {e}")

                elif target.login_method == 'credentials' and all([target.login_username, target.login_password, target.username_selector, target.password_selector, target.submit_button_selector]):
                    try:
                        wait = WebDriverWait(driver, 10)
                        user_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, target.username_selector)))
                        user_field.send_keys(target.login_username)
                        driver.find_element(By.CSS_SELECTOR, target.password_selector).send_keys(target.login_password)
                        driver.find_element(By.CSS_SELECTOR, target.submit_button_selector).click()
                        print("[*] 已提交登录表单，等待 5 秒让页面跳转...")
                        time.sleep(5)
                    except Exception as e: print(f"[!!!] 账号密码登录失败: {e}")

                current_img = get_screenshot(driver, target.url, target.screenshot_width, target.screenshot_max_height)
                screenshot_path = os.path.join(SCREENSHOT_DIR, target.screenshot_filename)
                
                if os.path.exists(screenshot_path):
                    print("[DEBUG] 发现旧快照，准备进行对比...")
                    last_img = Image.open(screenshot_path)
                    
                    img_to_compare_current = current_img.copy()
                    img_to_compare_last = last_img.copy()
                    try:
                        crop_box = json.loads(target.crop_area)
                        if isinstance(crop_box, list) and len(crop_box) == 4 and crop_box[2] > crop_box[0] and crop_box[3] > crop_box[1]:
                            print(f"[DEBUG] 应用裁剪区域进行对比: {crop_box}")
                            img_to_compare_current = img_to_compare_current.crop(tuple(crop_box))
                            img_to_compare_last = img_to_compare_last.crop(tuple(crop_box))
                    except (json.JSONDecodeError, TypeError, ValueError, IndexError): pass

                    if images_are_different(img_to_compare_last, img_to_compare_current, target.threshold):
                        print(f"[!!!] 检测到变化: {target.url}")
                        
                        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        target.last_changed = datetime.now()
                        
                        subject = f"网页变化提醒: {target.name or target.url}"
                        content = f"[{now_str}] 监控目标 '{target.name}' ({target.url}) 检测到页面发生视觉变化。"
                        tg_message = f"<b>网页变化提醒</b>\n\n<b>目标:</b> {target.name}\n<b>网址:</b> {target.url}\n\n检测到页面有新变化！\n<b>时间:</b> {now_str}"
                        
                        if notifications_config:
                            send_email(subject, content, notifications_config)
                            send_telegram_notification(tg_message, notifications_config)
                            send_bark_notification(subject, content, notifications_config)
                            send_pushplus_notification(subject, content, notifications_config)
                    else: print(f"[-] 页面无变化: {target.url}")
                else: print(f"[*] 首次截图，保存基准: {target.url}")

                current_img.save(screenshot_path)
                print(f"[DEBUG] 纯净快照已保存至: {screenshot_path}")
                
                target.last_checked = datetime.now()
                db.session.commit()
            except Exception as e:
                print(f"[!!!] 处理 {target.url} 时发生严重异常!")
                traceback.print_exc()
            finally:
                if driver:
                    print("[DEBUG] 正在关闭 webdriver...")
                    driver.quit()
                else:
                    print("[DEBUG] driver 未成功初始化，无需关闭。")
            print(f"--- 检查结束: {target.name or target.url} ---\n")
    finally:
        # [MODIFIED] 释放信号量
        browser_semaphore.release()

def sync_scheduler_from_db():
    with app.app_context():
        if scheduler.running: scheduler.remove_all_jobs()
        active_targets = MonitorTarget.query.filter_by(is_active=True).all()
        for target in active_targets:
            try:
                job_id = f'target_{target.id}'
                trigger = None
                schedule_info = ""
                
                if target.schedule_type == 'interval' and target.interval_minutes and target.interval_minutes > 0:
                    trigger = IntervalTrigger(minutes=target.interval_minutes, timezone='Asia/Shanghai')
                    schedule_info = f"每 {target.interval_minutes} 分钟"
                elif target.schedule_type == 'cron' and target.cron_schedule:
                    trigger = CronTrigger.from_crontab(target.cron_schedule, timezone='Asia/Shanghai')
                    schedule_info = f"Cron: '{target.cron_schedule}'"
                
                if trigger:
                    scheduler.add_job(
                        id=job_id, func=execute_target_check, args=[target.id],
                        trigger=trigger
                    )
                    print(f"[*] 已同步任务: {target.name or target.url} (ID: {target.id}), 调度: {schedule_info}")
                else:
                     print(f"[!] 任务配置无效，跳过: {target.name or target.url} (ID: {target.id})")
            except Exception as e: print(f"[!!!] 同步任务失败 for {target.url}: {e}")
        if scheduler.running:
            print(f"[*] 任务同步完成，当前共有 {len(scheduler.get_jobs())} 个任务在调度中。")

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
    if 'user_id' not in session: 
        return "Unauthorized", 401
    try:
        target_id_str = filename.replace('target_', '').replace('.png', '')
        target_id = int(target_id_str)
        target = MonitorTarget.query.get(target_id)
        screenshot_path = os.path.join(SCREENSHOT_DIR, filename)
        if not target or not os.path.exists(screenshot_path):
            return "File not found", 404
        crop_box = json.loads(target.crop_area or '[]')
        if isinstance(crop_box, list) and len(crop_box) == 4:
            image = Image.open(screenshot_path)
            draw = ImageDraw.Draw(image)
            draw.rectangle(crop_box, outline="red", width=5)
            img_io = io.BytesIO()
            image.save(img_io, 'PNG')
            img_io.seek(0)
            return send_file(img_io, mimetype='image/png')
        else:
            return send_from_directory(SCREENSHOT_DIR, filename)
    except (ValueError, json.JSONDecodeError, IndexError) as e:
        print(f"[WARN] 处理截图请求时出错: {e}")
        return send_from_directory(SCREENSHOT_DIR, filename)

@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    targets = MonitorTarget.query.order_by(MonitorTarget.id.desc()).all()
    notifications = NotificationSettings.query.first()
    return render_template('dashboard.html', targets=targets, notifications=notifications, now=datetime.now)

def process_schedule_form(form_data, target_obj):
    target_obj.schedule_type = form_data.get('schedule_type')
    if target_obj.schedule_type == 'interval':
        try:
            value = int(form_data.get('interval_value', 5))
            unit = form_data.get('interval_unit', 'minutes')
            if unit == 'hours': target_obj.interval_minutes = value * 60
            elif unit == 'days': target_obj.interval_minutes = value * 1440
            else: target_obj.interval_minutes = value
            target_obj.cron_schedule = None
        except (ValueError, TypeError):
            target_obj.interval_minutes = 5
    else:
        target_obj.cron_schedule = form_data.get('cron_schedule', '*/5 * * * *')
        target_obj.interval_minutes = None
    return target_obj

@app.route('/target/add', methods=['POST'])
def add_target():
    if 'user_id' not in session: return redirect(url_for('login'))
    new_target = MonitorTarget(
        name=request.form.get('name'), url=request.form.get('url'),
        screenshot_width=int(request.form.get('screenshot_width', 1920)),
        screenshot_max_height=int(request.form.get('screenshot_max_height', 15000)),
        threshold=int(request.form.get('threshold', 5)),
        crop_area=request.form.get('crop_area', '[]'),
        login_method=request.form.get('login_method'),
        cookies=request.form.get('cookies'),
        login_username=request.form.get('login_username'),
        login_password=request.form.get('login_password'),
        username_selector=request.form.get('username_selector'),
        password_selector=request.form.get('password_selector'),
        submit_button_selector=request.form.get('submit_button_selector'),
        is_active=request.form.get('is_active') == 'on'
    )
    new_target = process_schedule_form(request.form, new_target)
    db.session.add(new_target)
    db.session.commit()
    sync_scheduler_from_db()
    flash('监控目标已成功添加！', 'success')
    return redirect(url_for('dashboard'))

@app.route('/target/edit', methods=['POST'])
def edit_target():
    if 'user_id' not in session: return redirect(url_for('login'))
    target = MonitorTarget.query.get_or_404(request.form.get('target_id'))
    target.name = request.form.get('name')
    target.url = request.form.get('url')
    target.screenshot_width = int(request.form.get('screenshot_width'))
    target.screenshot_max_height = int(request.form.get('screenshot_max_height'))
    target.threshold = int(request.form.get('threshold'))
    target.crop_area = request.form.get('crop_area')
    target.login_method = request.form.get('login_method')
    target.cookies = request.form.get('cookies')
    target.login_username = request.form.get('login_username')
    target.login_password = request.form.get('login_password')
    target.username_selector = request.form.get('username_selector')
    target.password_selector = request.form.get('password_selector')
    target.submit_button_selector = request.form.get('submit_button_selector')
    target.is_active = request.form.get('is_active') == 'on'
    target = process_schedule_form(request.form, target)
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

@app.route('/target/execute/<int:target_id>', methods=['POST'])
def execute_manual_check(target_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    target = MonitorTarget.query.get_or_404(target_id)
    execute_target_check(target.id)
    flash(f"已手动为 '{target.name or target.url}' 触发了一次监控检查。", 'success')
    return redirect(url_for('dashboard'))

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
    settings.bark_url = request.form.get('bark_url')
    settings.pushplus_token = request.form.get('pushplus_token')
    db.session.add(settings)
    db.session.commit()
    flash('通知设置已成功保存！', 'success')
    return redirect(url_for('dashboard'))


# --- 6. 启动与初始化 ---
@app.cli.command("init-db")
def init_db():
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
    if not NotificationSettings.query.first():
        db.session.add(NotificationSettings())
        db.session.commit()
    
    if not scheduler.running:
        scheduler.start()
        print("[SCHEDULER] 后台调度器已成功启动。")
    
    print("[SCHEDULER] 应用启动，正在从数据库同步所有任务...")
    sync_scheduler_from_db()

if __name__ == '__main__':
    # 注意：直接运行此文件仅用于本地开发调试，生产环境请使用 Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=True)
