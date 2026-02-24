import json
import time
import os
import sys
import random
import subprocess
import shutil
import redis
import os
import time 
# Attempt imports, warn if missing
try:
    import pyautogui
    import pyperclip
    import pygetwindow as gw
except ImportError:
    print("Please install requirements: pip install pyautogui pyperclip pygetwindow redis")
    sys.exit(1)

from datetime import datetime
from urllib.parse import urlparse
# Redis Config
# Ideally load from settings or env, but for standalone script, we might need hardcoding or env vars
# Using same as settings.py
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = 'GODFATHER0220'
REDIS_QUEUE_KEY = 'boss_browser_command_queue'

SCROLL_DURATION = 15 
BROWSER_KEYWORDS = ["Boss", "直聘", "Chrome", "Google Chrome"]

def find_chrome_path():
    """Find Chrome executable"""
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.getenv('LOCALAPPDATA', ''), r"Google\Chrome\Application\chrome.exe")
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None

def launch_browser(url):
    """Launch Chrome with Proxy"""
    chrome_path = find_chrome_path()
    if not chrome_path:
        print("Chrome not found in standard locations.")
        return False
        
    print(f"Launching Chrome: {chrome_path}")
    try:
        # Launch with proxy and ignore certificate errors
        subprocess.Popen([
            chrome_path,
            "--proxy-server=127.0.0.1:8888",
            "--ignore-certificate-errors",
            "--new-window",
            "--blink-settings=imagesEnabled=false", # Disable images
            url
        ])
        time.sleep(5) # Wait for browser to open
        return True
    except Exception as e:
        print(f"Failed to launch Chrome: {e}")
        return False

def focus_browser():
    """Find and focus the browser window"""
    target_window = None
    windows = gw.getAllTitles()
    
    # Priority search
    for keyword in BROWSER_KEYWORDS:
        for title in windows:
            if keyword in title:
                # Get the window object
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    target_window = wins[0]
                    break
        if target_window:
            break
            
    if target_window:
        print(f"Focusing Window: {target_window.title}")
        try:
            if target_window.isMinimized:
                target_window.restore()
            target_window.activate()
            time.sleep(0.5)
            return True
        except Exception as e:
            print(f"Failed to focus window: {e}")
            return False
    else:
        print("Browser window not found!")
        return False

def perform_browsing(url):
    print(f"Propagating Task: {url}")
    
    # 1. Focus or Launch
    if not focus_browser():
        print("Attempting validation launch...")
        if launch_browser(url):
             # Try focus again after launch
             if not focus_browser():
                 print("Launched but could not focus. Requesting manual intervention.")
        else:
             print("Could not launch browser.")
             return
    
    # 2. Navigate (Double check URL)
    print("Navigating...")
    
    pyperclip.copy(url)
    time.sleep(0.1)
    
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.1)
    
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.1)
    
    pyautogui.press('enter')
    
    print("Waiting for page load...")
    
    # Reduced from 3 to 1. The MITM intercepts the request quickly.
    time.sleep(1) 
    
    print(f"Waiting for next command...")

def main():
    print("=============================================")
    print("   Boss Controller (Redis Mode) Started      ")
    print("   Queue: " + REDIS_QUEUE_KEY)
    print("=============================================")
    
    # Redis Connection
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
        r.ping()
        print("   Connected to Redis successfully.")
    except Exception as e:
        print(f"   Failed to connect to Redis: {e}")
        sys.exit(1)

    while True:
        try:
            # BLPOP blocks until an item is available
            # Returns tuple (key, value)
            print("   等待任务...", end='\r')
            item = r.blpop(REDIS_QUEUE_KEY, timeout=5)
            
            if item:
                _, payload = item
                data = json.loads(payload)
                url = data.get('url')
                parsed_path = urlparse(url).path       # 提取 /job_detail/12345.html (自动去掉 ?ka=...)
                filename = os.path.basename(parsed_path) # 提取 12345.html
                job_id = filename.replace(".html", "")   # 提取 12345
                
                print(f"\n   收到任务: {url}")
                perform_browsing(url)
                
                # Wait for Spider to signal completion (Done or Timeout)
                print(f"等待数据抓取 (Job: {job_id})...")
                start_wait = time.time()
                while True:
                    status = r.get(job_id)
                    
                    if status in ['done', 'timeout', 'error']:
                        print(f"   任务完成，状态: {status}")
                        time.sleep(1)
                        break
                    
                    if status is None:
                        # Key disappeared (expired or deleted) without marking done?
                        # Or maybe it was never set? Spider sets it 'processing' immediately.
                        # We should treat this as done/unknown if enough time passed.
                        if time.time() - start_wait > 5: 
                             print("   任务状态键丢失。假设已完成。")
                             break
                    
                    if time.time() - start_wait > 15: # Failsafe > Spider Timeout (60s)
                        print("   Controller 等待超时 (70s)。强制进入下一个。")
                        break
                        
                    
                
        except KeyboardInterrupt:
            print("\n停止 Controller。")
            break
        except Exception as e:
            print(f"\nError in loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    pyautogui.FAILSAFE = True
    main()
