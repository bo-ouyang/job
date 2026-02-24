import json
import time
import os
import sys
import subprocess
import redis
import pyautogui
import pygetwindow as gw
import pyperclip
from urllib.parse import urlparse

from dotenv import load_dotenv

# Load .env from jobCollectionWebApi
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))) # d:/Code/job
env_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=env_path)

# Redis Config (Same as settings.py / detail controller)
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_QUEUE_KEY = 'boss_monitor_command_queue'

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
        # Note: Monitor might need images enabled to see CAPTCHA? Detail disables them.
        # User asked to disable images earlier for detail. For monitor, maybe keep enabled if captcha is frequent?
        # But 'mimic boss_detail' implies efficiency. I'll disable images but check user preference.
        # Note: Boss list (monitor) relies on raw DOM parsing from Scrapy, not Mitmproxy responses
        # So we MUST NOT use the 8888 proxy here unless explicitly Mitmproxy is running for this spider
        # CRITICAL: We MUST use an isolated user-data-dir, otherwise Chrome will merge with an existing open
        # browser instance, entirely ignoring our proxy-server flag and causing "Check Proxy" errors.
        #user_data_dir = os.path.join(current_dir, "chrome_isolated_data")
        subprocess.Popen([
            chrome_path,
            #f"--user-data-dir={user_data_dir}",
            "--proxy-server=127.0.0.1:8889",
            "--ignore-certificate-errors",
            "--new-window",
            "--blink-settings=imagesEnabled=false", 
            url
        ])
        time.sleep(3) # Wait for browser to open
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
        # print(f"Focusing Window: {target_window.title}")
        try:
            if target_window.isMinimized:
                target_window.restore()
            target_window.activate()
            time.sleep(0.5)
            return True
        except Exception as e:
            # print(f"Failed to focus window: {e}")
            return False
    else:
        # print("Browser window not found!")
        return False

def perform_browsing(url, req_id, r):
    print(f"Navigating to: {url}")
    
    # 1. Focus or Launch
    if not focus_browser():
        print("Attempting validation launch...")
        if launch_browser(url):
             time.sleep(2)
             if not focus_browser():
                 print("Launched but could not focus. Requesting manual intervention.")
        else:
             print("Could not launch browser.")
             return
    
    # 2. Navigate (One time)
    pyperclip.copy(url)
    time.sleep(0.1)
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.1)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.1)
    pyautogui.press('enter')
    
    time.sleep(2) 

    # 3. Scroll Loop
    page_num = 1
    while True:
        print(f"   [Page {page_num}] Scrolling for data...")
        # Scroll down to trigger load (multiple small scrolls to mimic human)
        #for _ in range(3):
        pyautogui.scroll(-1200)
        time.sleep(1)
        # Wait for Spider Signal (req_id status)
        print(f"   Waiting for spider signal (ReqID: {req_id})...")
        
        # Check Status
        status = r.get(req_id)
        if status == 'done':
            print(f"   Task Completed (Signal: {status}).")
            time.sleep(1)
            break # Exit Function
        
        
            
            
        

def main():
    print("=============================================")
    print("   Boss Monitor Controller (Redis Scroll Mode)")
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
            print("   等待监控任务 (Peek Mode)...", end='\r')
            # Peek at the first item without removing
            payload = r.lindex(REDIS_QUEUE_KEY, 0)
            
            if payload:
                # 1. Parse Data
                try:
                    data = json.loads(payload)
                    url = data.get('url')
                    req_id = data.get('req_id')
                except json.JSONDecodeError:
                    print(f"\n   Error decoding JSON. Popping invalid item.")
                    r.lpop(REDIS_QUEUE_KEY)
                    continue
                
                # 2. Check Completion Status
                status = r.get(req_id)
                
                if status == 'done':
                    print(f"\n   任务完成 (ReqID: {req_id})。从队列移除。")
                    r.lpop(REDIS_QUEUE_KEY)
                    time.sleep(1)
                    continue
                
                # 3. Process Task (Resume or Start)
                # If status is 'more' or None, we continue processing
                print(f"\n   处理任务: {url} (Status: {status})")
                perform_browsing(url, req_id, r)
                
                # Note: perform_browsing returns when it sees 'done' (or timeout/error? current implementation loops until done/timeout)
                # We loop back. Next iteration will check status 'done' and pop it.
                
            else:
                # Queue Empty
                time.sleep(2)
                
        except KeyboardInterrupt:
            print("\n停止 Controller。")
            break
        except Exception as e:
            print(f"\nError in loop: {e}")
            time.sleep(1)

if __name__ == '__main__':
    main()
