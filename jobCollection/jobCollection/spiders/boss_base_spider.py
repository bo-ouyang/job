import scrapy
import subprocess
import time
import os
import asyncio
from aiohttp import web
from scrapy import signals
from scrapy.exceptions import DontCloseSpider
from common.databases.PostgresManager import db_manager
import json
from urllib.parse import urlparse
class BossBaseSpider(scrapy.Spider):
    # Subclasses should define these
    name = "boss_base"
    TASK_FILE = "task_status.json" 
    
    custom_settings = {
        "DOWNLOAD_TIMEOUT": 1800,
        "CONCURRENT_REQUESTS": 1,
    }

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super(BossBaseSpider, cls).from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mitm_process = None
        # self.web_runner = None
        # self.site = None
        self.item_queue = asyncio.Queue()
        self.is_checking = False
        self.logger.info(f"Initialized {self.name} with Task File: {self.TASK_FILE}")
        
        # Redis Setup
        import redis
        from jobCollection.settings import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB, UPSTREAM_PROXY, PROXY_ROTATE_MINUTES, ENABLE_UPSTREAM_PROXY
        
        self.redis_client = redis.Redis(
            host=REDIS_HOST, 
            port=REDIS_PORT, 
            db=REDIS_DB, 
            password=REDIS_PASSWORD, 
            decode_responses=True
        )
        self.redis_key = "boss_spider_data_queue"
        
        self.enable_upstream_proxy = ENABLE_UPSTREAM_PROXY
        self.upstream_proxy = UPSTREAM_PROXY
        self.proxy_rotate_minutes = PROXY_ROTATE_MINUTES
        self.mitm_start_time = None

    async def start_mitmproxy(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        addon_path = os.path.join(root_dir, "boss_mitm_addon.py")
        
        if not os.path.exists(addon_path):
             addon_path = "boss_mitm_addon.py" 
        
        # Ensure task file exists
        if not os.path.exists(self.TASK_FILE):
             with open(self.TASK_FILE, 'w', encoding='utf-8') as f:
                 f.write("{}")

        # Dynamic mitmdump path
        import sys
        mitmdump_path = "mitmdump" # Fallback
        
        # Try finding in Scripts folder relative to python executable
        scripts_dir = os.path.join(os.path.dirname(sys.executable), 'Scripts')
        potential_path = os.path.join(scripts_dir, 'mitmdump.exe')
        
        if os.path.exists(potential_path):
            mitmdump_path = potential_path
            self.logger.info(f"Found mitmdump at: {mitmdump_path}")
        else:
            self.logger.warning(f"mitmdump not found at {potential_path}, using default 'mitmdump' command")

        cmd = [mitmdump_path, "-s", addon_path, "-p", "8889", "-q", "--ssl-insecure"]
        
        # Fetch Proxy from DB (Only if enabled)
        if self.enable_upstream_proxy:
            try:
                from common.databases.models.proxy import Proxy
                from sqlalchemy import select, func
                
                async with (await db_manager.get_session()) as session:
                     # Get a random active proxy
                     stmt = select(Proxy).where(Proxy.is_active == True).order_by(func.random()).limit(1)
                     result = await session.execute(stmt)
                     db_proxy = result.scalar_one_or_none()
                     
                     if db_proxy:
                         proxy_url = f"{db_proxy.protocol}://{db_proxy.ip}:{db_proxy.port}"
                         self.upstream_proxy = proxy_url # Update local record
                         
                         cmd.extend(["--mode", f"upstream:{proxy_url}"])
                         self.logger.info(f"Using DB Proxy: {proxy_url}")
                     else:
                         self.logger.warning("No active proxies found in DB! Proceeding without proxy.")
            except Exception as e:
                self.logger.error(f"Failed to fetch proxy from DB: {e}")
        else:
             self.logger.info("Upstream Proxy is DISABLED in settings. Proceeding with direct connection.")

        self.logger.info(f"Starting Mitmproxy: {' '.join(cmd)}")
        try:
            self.mitm_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.PIPE,
                cwd=root_dir 
            )
            
            if self.mitm_process.poll() is not None:
                _, err = self.mitm_process.communicate()
                self.logger.error(f"Mitmproxy failed to start: {err.decode('utf-8', errors='ignore')}")
            else:
                self.logger.info("=================================================")
                self.logger.info(f"   Mitmproxy Started ({self.name})             ")
                if self.upstream_proxy:
                     self.logger.info(f"   Upstream Proxy: {self.upstream_proxy} (Roate: {self.proxy_rotate_minutes}m)")
                self.logger.info("   Listening for Data via Redis Queue            ")
                self.logger.info("=================================================")
                self.mitm_start_time = time.time()
        except Exception as e:
            self.logger.error(f"Failed to start mitmproxy: {e}")

    # async def start_web_server(self): ... REMOVED

    async def start(self):
        """Async initialization and start"""
        self.logger.info(f"Starting {self.name} components...")
        await db_manager.initialize() # Initialize DB first to fetch proxy
        await self.start_mitmproxy()
        # await self.start_web_server()
        
        yield scrapy.Request("data:,started", callback=self.parse_loop, dont_filter=True)

    async def parse_loop(self, response):
        """Main Loop: Yield Items -> Check Redis -> Check Task -> Sleep"""
        # 1. Yield items
        while not self.item_queue.empty():
            item = await self.item_queue.get()
            yield item

        # 2. Check Redis for Data
        await self.check_redis_data()

        # 3. Sync / Check Task
        if not self.is_checking:
             self.is_checking = True
             try:
                 await self.check_task_logic()
             except Exception as e:
                 self.logger.error(f"Task Logic Error: {e}")
             finally:
                 self.is_checking = False
        
        # 4. Check Proxy Rotation
        await self.check_proxy_rotation()
        
        await asyncio.sleep(0.1) # Faster polling
        yield scrapy.Request("data:,loop", callback=self.parse_loop, dont_filter=True)

    async def check_proxy_rotation(self):
        """Check if we need to restart mitmproxy to rotate IP"""
        if self.upstream_proxy and self.proxy_rotate_minutes > 0 and self.mitm_start_time:
            elapsed = (time.time() - self.mitm_start_time) / 60
            if elapsed >= self.proxy_rotate_minutes:
                self.logger.info(f"Proxy Rotation Interval ({self.proxy_rotate_minutes}m) Reached. Restarting Mitmproxy...")
                await self.restart_mitmproxy()

    async def restart_mitmproxy(self):
        """Restart Mitmproxy process"""
        if self.mitm_process:
            self.logger.info("Stopping Mitmproxy...")
            self.mitm_process.terminate()
            try:
                self.mitm_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.mitm_process.kill()
            self.mitm_process = None
        
        self.logger.info("Restarting Mitmproxy...")
        await self.start_mitmproxy()

    async def check_redis_data(self):
        """Read items from Redis List"""
        try:
            data_str = self.redis_client.lpop(self.redis_key)
            #print(self.redis_key)
            if data_str:
                import json
                data = json.loads(data_str)
                await self.handle_redis_data(data)
                
        except Exception as e:
            self.logger.error(f"Redis Error: {e}")

    async def handle_redis_data(self, data):
        """Subclasses can override"""
        pass

    async def check_task_logic(self):
        """Subclasses implement specific task logic here"""
        pass

    def spider_idle(self, spider):
        self.crawler.engine.crawl(
            scrapy.Request("data:,idle", callback=self.parse_loop, dont_filter=True), 
            spider
        )
        raise DontCloseSpider

    async def spider_closed(self, spider):
        self.logger.info("Closing spider...")
        if self.mitm_process:
            self.mitm_process.terminate()
            try:
                self.mitm_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.mitm_process.kill()
        
        self.redis_client.close()

    async def push_browser_command(self, url):
        """Push navigation command to Redis for the GUI Controller"""
        try:
            payload = json.dumps({"url": url, "timestamp": time.time()})
            self.redis_client.rpush("boss_browser_command_queue", payload)
            
            self.logger.info(f"Pushed Browser Command: {url}")
        except Exception as e:
            self.logger.error(f"Failed to push browser command: {e}")
