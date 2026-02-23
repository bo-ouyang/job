import json
import time
import os
import sys
import redis
from datetime import datetime
from urllib.parse import urlparse

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:
    print("Please install requirements: pip install DrissionPage redis")
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

def get_browser():
    """Configure and launch ChromiumPage"""
    co = ChromiumOptions()
    
    # Proxy Configuration (Point to Mitmproxy)
    co.set_proxy("127.0.0.1:8888")
    
    # Efficiency Settings
    co.set_argument("--blink-settings=imagesEnabled=false") # Disable images
    co.set_argument("--ignore-certificate-errors")
    co.mute(True) # Mute audio
    
    # Use existing Chrome if available, or launch new one
    # DrissionPage handles this automatically usually, but let's be explicit about port if needed
    # co.set_local_port(9222) 
    
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
    try:
        page = get_browser()
        print("   Browser Initialized.")
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
                    page.get(url)
                    # No need to wait for full load if we rely on Mitmproxy interception
                    # But a small wait helps ensure the request goes out
                    time.sleep(0.5) 
                except Exception as e:
                    print(f"   Browser Error: {e}")
                
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
            break
        except Exception as e:
            print(f"\nError in loop: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
