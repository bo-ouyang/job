import json
import asyncio
import logging
import aiohttp
from mitmproxy import http
from datetime import datetime
# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import redis.asyncio as redis
import sys
import os

# Import our new proxy manager
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.append(current_dir)
    from proxy_manager import proxy_manager
except ImportError as e:
    logger.error(f"Could not import proxy_manager: {e}")
    proxy_manager = None
try:
    from jobCollection.settings import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB
except ImportError:
    # Fallback if import fails (e.g. mitmproxy env different)
    import os
    from dotenv import load_dotenv
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    load_dotenv(os.path.join(project_root, '.env'))
    
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
pool = redis.ConnectionPool(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)

class BossRecJobInterceptor:
    def __init__(self):
        self.target_url_partial = "/job/list.json"
        self.bridge_url = "http://localhost:9090/submit"

    async def push_to_redis(self, url, data, has_more, type="list"):
        client = redis.Redis(connection_pool=pool)
        # Payload
        payload = {
            "url": url,
            "data": data,
            "has_more": has_more,
            "type": type 
        }
        try:
            # Add project root to path to allow importing settings
            current_dir = os.path.dirname(os.path.abspath(__file__))
            if current_dir not in sys.path:
                sys.path.append(current_dir)
        
            
            # Determine Queue Key
            queue_key = "boss_spider_data_queue" # Fallback
            if type == "list":
                queue_key = "boss_spider_list_queue"
            elif type == "detail_html":
                queue_key = "boss_spider_detail_queue"
            
            await client.rpush(queue_key, json.dumps(payload))
            await client.close()
            
            logger.info(f"Pushed data to Redis for {url}")

        except Exception as e:
            logger.error(f"Failed to push to Redis: {e}. Is the spider running?")
    async def response(self, flow: http.HTTPFlow):
        # 1. List Page Interception
        if self.target_url_partial in flow.request.url:
            if flow.response.status_code == 200:
                try:
                    data = json.loads(flow.response.content)
                    zp_data = data.get('zpData', {})
                    
                    #if zp_data and zp_data.get('jobList'):
                    job_list = zp_data.get('jobList',[])
                    has_more = zp_data.get('hasMore', False)

                    # with open(TASK_FILE, 'w', encoding='utf-8') as f:
                    #     json.dump({'has_more': has_more, 'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False, indent=2)
                    logger.info(f"Intercepted {len(job_list)} jobs from List. hasMore: {has_more}")
                    await self.push_to_redis(flow.request.url, job_list, has_more, type="list")
                            
                except Exception as e:
                    logger.error(f"Failed to process List response: {e}")
        
        # 2. Detail Page Interception (HTML)
        elif "www.zhipin.com/job_detail" in flow.request.url and "text/html" in flow.response.headers.get("Content-Type", ""):
            # 增加对 403/302 的检查
            if flow.response.status_code in [403, 302]:
                logger.warning(f"IP blocked or Redirected: {flow.request.url}")
                # 应该推送一个错误信号给 Redis，而不是忽略
                await self.push_to_redis(flow.request.url, None, None, type="detail_html")
            if flow.response.status_code == 200:
                try:
                    html_content = flow.response.text
                    # Simple check to ensure it's a valid job page
                    if "job-sec-text" in html_content:
                        logger.info(f"Intercepted Job Detail HTML: {flow.request.url}")
                        await self.push_to_redis(flow.request.url, html_content, has_more=None, type="detail_html")
                except Exception as e:
                    logger.error(f"Failed to process Detail response: {e}")

    def request(self, flow: http.HTTPFlow):
        """ Dynamically route requests through KDL proxy """
        if proxy_manager is None:
            return
            
        # Don't proxy local requests or our bridge
        if "localhost" in flow.request.host or "127.0.0.1" in flow.request.host or flow.request.host == "dps.kdlapi.com":
            return
            
        current_proxy = proxy_manager.get_proxy()
        if current_proxy:
            # Format: http://user:pass@ip:port
            try:
                # Remove http://
                proxy_str = current_proxy.replace("http://", "")
                auth_part, ip_port_part = proxy_str.split("@")
                user, pwd = auth_part.split(":")
                proxy_ip, proxy_port = ip_port_part.split(":")
                
                # Set upstream proxy for this specific flow
                flow.server_conn.via = http.server.UpstreamProxy(
                    address=(proxy_ip, int(proxy_port)),
                    auth=(user, pwd)
                )
                # logger.info(f"Routed via proxy: {proxy_ip}")
            except Exception as e:
                logger.error(f"Failed to set upstream proxy: {e}")


addons = [
    BossRecJobInterceptor()
]
