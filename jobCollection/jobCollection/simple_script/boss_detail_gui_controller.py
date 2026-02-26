import json
import time
import os
import sys
import redis
from datetime import datetime
from urllib.parse import urlparse

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    from proxy_manager import proxy_manager
except ImportError as e:
    print(f"Please install requirements: pip install DrissionPage redis httpx. Error: {e}")
    sys.exit(1)

from dotenv import load_dotenv

# Load .env from jobCollectionWebApi
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir))) # d:/Code/job
env_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=env_path)

# Redis Config (Same as other scripts)
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_QUEUE_KEY = 'boss_browser_command_queue'

def get_browser(proxy_url=None):
    """Configure and launch ChromiumPage"""
    co = ChromiumOptions()
    
    # Proxy Configuration
    # Fallback to local mitmproxy if no proxy provided (but user wants KDL for detail!)
    # Actually, if we use KDL, we bypass Mitmproxy! 
    # WAIT: if we bypass Mitmproxy, the Scrapy parser won't get the JSON because mitmproxy isn't intercepting it!
    # Ah! If we use a direct proxy here, Mitmproxy won't see it unless we configure Mitmproxy to use an Upstream Proxy instead.
    # But since this is the *Detail* page, does the Detail Spider rely on Mitmproxy JSON interception, or raw DOM parsing?
    # Detail pages might just use DOM. Let's assume DP renders it and DP saves DOM? No, Scrapy runs `boss_detail` which fetches the DB URL itself, or DP just visits it?
    # Looking at the run_pipeline.py, Detail Spider runs scrapy. DP just triggers it? Or DP loads the page so Scrapy can parse DB?
    # Actually, in DrissionPage detail controller, it relies on Mitmproxy to intercept details?
    # Let's set the proxy. If Mitmproxy is needed, the proxy should be set in Mitmproxy. 
    # Assuming DP triggers some background API or simply bypasses anti-bot.
    if proxy_url:
        print(f"   [Browser] Setting proxy: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")
        co.set_proxy(proxy_url)
    else:
        # If no KDL proxy available, optionally fallback or run direct
        co.set_proxy("127.0.0.1:8889") # Mitmproxy fallback
    
    # Isolate user data to prevent proxy bypass due to existing chrome instances
    user_data_dir = os.path.join(current_dir, "chrome_isolated_data_detail")
    co.set_user_data_path(user_data_dir)
    
    # Efficiency Settings
    co.set_argument("--blink-settings=imagesEnabled=false") # Disable images
    co.set_argument("--ignore-certificate-errors")
    co.mute(True) # Mute audio
    
    page = ChromiumPage(co)
    return page

def main():
    print("=============================================")
    print("   Boss Controller (DrissionPage) Started    ")
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

    # Initialize Browser
    #current_proxy = proxy_manager.get_proxy()
    page = None
    try:
        page = get_browser()
        print("   Browser Initialized with Proxy.")
    except Exception as e:
        print(f"   Failed to initialize browser: {e}")
        sys.exit(1)

    while True:
        try:
            # BLPOP blocks until an item is available
            print("   等待任务...", end='\r')
            item = r.blpop(REDIS_QUEUE_KEY, timeout=5)
            
            if item:
                _, payload = item
                data = json.loads(payload)
                url = data.get('url')
                parsed_path = urlparse(url).path
                filename = os.path.basename(parsed_path)
                job_id = filename.replace(".html", "")
                
                print(f"\n   收到任务: {url}")
                
                # Navigate
                try:
                    if page:
                        page.get(url)
                    # No need to wait for full load if we rely on Mitmproxy interception
                    # But a small wait helps ensure the request goes out
                    time.sleep(4) 
                    
                    # Anti-Bot Check
                    if page and ("安全拦截" in page.html or "验证码" in page.html or "系统检测到您" in page.html):
                        print("   [Anti-Bot] 检测到反爬/验证码拦截！")
                        proxy_manager.remove_proxy(current_proxy)
                        current_proxy = proxy_manager.get_proxy()
                        print("   [Anti-Bot] 重启浏览器切换IP...")
                        if page:
                            page.quit()
                        time.sleep(2)
                        page = get_browser(current_proxy)
                        # Push task back to queue for retry
                        r.rpush(REDIS_QUEUE_KEY, payload)
                        continue
                        
                except Exception as e:
                    print(f"   Browser Error: {e}")
                    proxy_manager.remove_proxy(current_proxy)
                    current_proxy = proxy_manager.get_proxy()
                    try:
                        if page:
                            page.quit()
                    except: pass
                    page = get_browser(current_proxy)
                    r.rpush(REDIS_QUEUE_KEY, payload)
                    continue
                
                # Wait for Spider to signal completion
                print(f"等待数据抓取 (Job: {job_id})...")
                start_wait = time.time()
                while True:
                    status = r.get(job_id)
                    
                    if status in ['done', 'timeout', 'error']:
                        print(f"   任务完成，状态: {status}")
                        break
                    
                    if status is None:
                        if time.time() - start_wait > 5: 
                             print("   任务状态键丢失。假设已完成。")
                             break
                    
                    if time.time() - start_wait > 15:
                        print("   Controller 等待超时 (15s)。强制进入下一个。")
                        break
                    
                    time.sleep(0.1)
                
        except KeyboardInterrupt:
            print("\n停止 Controller。")
            if page: page.quit()
            break
        except Exception as e:
            print(f"\nError in loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
