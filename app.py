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
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- 1. 初始化应用、数据库和调度器 ---
app = Flask(__name__)

# 确保 instance 和 screenshots 文件夹存在
if not os.path.exists('instance'): os.makedirs('instance')
SCREENSHOT_DIR = "/app/screenshots"
if not os.path.exists(SCREENSHOT_DIR): os.makedirs(SCREENSHOT_DIR)

# 配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_and_secure_key_for_development')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(app.instance_path, 'monitoring.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
scheduler = BackgroundScheduler(daemon=True, timezone='Asia/Shanghai')


# --- 2. 数据库模型 (不变) ---
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

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


# --- 3. 辅助函数 (不变) ---
# ... (get_screenshot, images_are_different, etc. 保持不变) ...


# --- 4. 核心监控与调度逻辑 (关键修改：移除了旧的 scheduler.start() 调用) ---
def execute_target_check(target_id):
    # ... (此函数内部逻辑不变) ...
    pass

def sync_scheduler_from_db():
    """从数据库同步所有监控任务到调度器 (不再负责启动调度器)"""
    with app.app_context():
        # 先清除所有旧任务，防止重复
        if scheduler.running:
            scheduler.remove_all_jobs()
        
        active_targets = MonitorTarget.query.filter_by(is_active=True).all()
        for target in active_targets:
            try:
                scheduler.add_job(
                    id=f'target_{target.id}', func=execute_target_check, args=[target.id],
                    trigger=CronTrigger.from_crontab(target.cron_schedule, timezone='Asia/Shanghai')
                )
                print(f"[*] 已同步任务: {target.name or target.url} (ID: {target.id}), 调度: '{target.cron_schedule}'")
            except Exception as e:
                print(f"[!!!] 同步任务失败 for {target.url}: {e}")
        
        # 打印当前所有任务，便于调试
        if scheduler.running:
            print(f"[*] 任务同步完成，当前共有 {len(scheduler.get_jobs())} 个任务在调度中。")

# --- 5. Web 路由 (不变) ---
# ... (所有 @app.route 函数保持不变) ...


# --- 6. 启动与初始化 (关键修改) ---
@app.cli.command("init-db")
def init_db():
    # ... (此函数不变) ...
    pass

# --- 【关键修正】重构应用启动逻辑 ---
with app.app_context():
    db.create_all()
    # 确保至少有一个通知设置行存在
    if not NotificationSettings.query.first():
        db.session.add(NotificationSettings())
        db.session.commit()
    
    # 1. 明确地启动调度器（如果它尚未运行）
    if not scheduler.running:
        scheduler.start()
        print("[SCHEDULER] 后台调度器已成功启动。")
    else:
        print("[SCHEDULER] 后台调度器已在运行中。")
        
    # 2. 启动时同步一次数据库中的任务
    print("[SCHEDULER] 应用启动，正在从数据库同步所有任务...")
    sync_scheduler_from_db()
