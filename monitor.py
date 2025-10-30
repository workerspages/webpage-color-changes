#!/usr/bin/env python3

import subprocess
import sys
import io
import os
import requests
import json
import time  # <-- 1. 新增：导入时间模块
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 从环境变量加载配置 ---
# (这部分保持不变)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TO_EMAIL = os.getenv("TO_EMAIL")
MONITOR_URLS = os.getenv("MONITOR_URLS", "")
SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/app/screenshots")
THRESHOLD = int(os.getenv("THRESHOLD", "50"))
CROP_AREAS_JSON = os.getenv("CROP_AREAS", "{}") 
SCREENSHOT_WIDTH = int(os.getenv("SCREENSHOT_WIDTH", "1920"))
SCREENSHOT_MAX_HEIGHT = int(os.getenv("SCREENSHOT_MAX_HEIGHT", "15000"))


# --- 浏览器配置 (核心修改) ---
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage') # 在 Docker 中推荐
chrome_options.add_argument('--lang=zh-CN')
chrome_options.add_argument('--font-render-hinting=medium')
# --- 2. 新增：在浏览器启动时就强制设定窗口大小 ---
INITIAL_HEIGHT = 1080  # 设置一个初始高度，后续脚本会根据页面实际高度调整
chrome_options.add_argument(f'--window-size={SCREENSHOT_WIDTH},{INITIAL_HEIGHT}')


def get_screenshot(driver, url):
    """加强版的截图函数，增加了延时和调试日志"""
    print(f"正在以 {SCREENSHOT_WIDTH}px 目标宽度访问 {url}...")
    driver.get(url)
    
    total_height = driver.execute_script("return document.body.scrollHeight")
    if total_height > SCREENSHOT_MAX_HEIGHT:
        print(f"警告：页面高度 {total_height}px 超过最大值 {SCREENSHOT_MAX_HEIGHT}px，将进行截断。")
        total_height = SCREENSHOT_MAX_HEIGHT
    
    # 即使启动时设置了，这里再设置一次以确保高度正确
    driver.set_window_size(SCREENSHOT_WIDTH, total_height)
    
    # --- 3. 核心修改：等待渲染并增加调试日志 ---
    print("等待 2 秒让页面根据窗口大小重新渲染...")
    time.sleep(2)
    
    # 打印浏览器报告的当前实际窗口大小
    actual_size = driver.get_window_size()
    print(f"浏览器报告的实际窗口尺寸: {actual_size['width']}x{actual_size['height']}")

    png = driver.get_screenshot_as_png()
    img = Image.open(io.BytesIO(png))
    return img

def images_are_different(img1, img2, threshold):
    diff = ImageChops.difference(img1, img2)
    if diff.getbbox() is None:
        return False
    diff_sum = sum(diff.histogram())
    return diff_sum > threshold

def send_email(subject, content, to_email):
    if not to_email:
        print("接收邮箱地址未配置 (TO_EMAIL)，跳过邮件发送。")
        return
    email_text = f"Subject: {subject}\n\n{content}"
    try:
        process = subprocess.Popen(['msmtp', to_email], stdin=subprocess.PIPE)
        process.communicate(email_text.encode('utf-8'))
        print(f"邮件已发送至 {to_email}。")
    except FileNotFoundError:
        print("错误：msmtp 命令未找到。请确保它已安装并在系统 PATH 中。")
    except Exception as e:
        print(f"发送邮件时发生错误: {e}")

def send_telegram_notification(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Bot Token 或 Chat ID 未配置，跳过发送。")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            print("Telegram 通知发送成功。")
        else:
            print(f"发送 Telegram 通知失败: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"发送 Telegram 通知时发生异常: {e}")

def main():
    urls = [url.strip() for url in MONITOR_URLS.split(',') if url.strip()]
    if not urls:
        print("错误：没有配置需要监控的网址 (MONITOR_URLS)。请在 docker-compose.yml 中设置。")
        sys.exit(1)

    try:
        crop_areas = json.loads(CROP_AREAS_JSON)
        if crop_areas:
            print(f"已加载指定监控区域: {crop_areas}")
    except json.JSONDecodeError:
        print(f"错误：CROP_AREAS 环境变量格式不正确，必须是有效的 JSON。已忽略所有裁剪设置。")
        crop_areas = {}
    
    driver = webdriver.Chrome(options=chrome_options)
    try:
        if not os.path.exists(SCREENSHOT_DIR):
            os.makedirs(SCREENSHOT_DIR)

        for url in urls:
            print(f"--- 正在检查: {url} ---")
            try:
                current_img = get_screenshot(driver, url)
                file_name = url.replace("https://", "").replace("http://", "").replace("/", "_") + ".png"
                screenshot_path = os.path.join(SCREENSHOT_DIR, file_name)

                if os.path.exists(screenshot_path):
                    last_img = Image.open(screenshot_path)

                    img_to_compare_current = current_img
                    img_to_compare_last = last_img
                    
                    if url in crop_areas:
                        crop_box = tuple(crop_areas[url])
                        print(f"为 {url} 应用裁剪区域: {crop_box}")
                        try:
                            img_to_compare_current = current_img.crop(crop_box)
                            img_to_compare_last = last_img.crop(crop_box)
                        except Exception as e:
                            print(f"裁剪图片时出错: {e}。将退回对比完整图片。")

                    if images_are_different(img_to_compare_last, img_to_compare_current, THRESHOLD):
                        subject = f"[网页变化提醒] {url} 页面发生变化"
                        content = f"网址 {url} 的页面检测到变化，请及时查看。"
                        tg_message = f"<b>网页变化提醒</b>\n\n检测到页面有新变化！\n<b>网址:</b> {url}"
                        
                        send_email(subject, content, TO_EMAIL)
                        send_telegram_notification(tg_message)
                    else:
                        print(f"页面无变化。")
                else:
                    print(f"首次截图，保存基准快照。")

                current_img.save(screenshot_path)

            except Exception as e:
                print(f"处理 {url} 时发生异常: {e}")
                error_message = f"<b>监控脚本异常</b>\n\n处理网址 {url} 时发生错误:\n<pre>{e}</pre>"
                send_telegram_notification(error_message)

    finally:
        driver.quit()
    print("--- 本轮检查完成 ---")

if __name__ == '__main__':
    main()
