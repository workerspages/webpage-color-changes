#!/usr/bin/env python3

import subprocess
import sys
import io
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from PIL import Image, ImageChops

# --- 从环境变量加载配置 ---
# 必填项
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TO_EMAIL = os.getenv("TO_EMAIL")
# 监控的网址，以逗号分隔
MONITOR_URLS = os.getenv("MONITOR_URLS", "") 
# 可选项，提供默认值
SCREENSHOT_DIR = os.getenv("SCREENSHOT_DIR", "/app/screenshots")
THRESHOLD = int(os.getenv("THRESHOLD", "50"))

# --- 浏览器配置 ---
chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage') # 在 Docker 中推荐
chrome_options.add_argument('--lang=zh-CN')
chrome_options.add_argument('--font-render-hinting=medium')

def get_screenshot(driver, url):
    driver.get(url)
    max_height = 10000
    total_height = driver.execute_script("return document.body.scrollHeight")
    if total_height > max_height:
        total_height = max_height
    driver.set_window_size(1200, total_height)
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
                    if images_are_different(last_img, current_img, THRESHOLD):
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
