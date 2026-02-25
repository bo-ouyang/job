import json
import os
import time
import asyncio
from datetime import datetime
import scrapy
from scrapy import Selector
from sqlalchemy import select, update
from urllib.parse import urlparse

# DrissionPage and Proxy Manager
from DrissionPage import ChromiumPage, ChromiumOptions

# DB Models
from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job

# To load proxy_manager correctly depending on execution context run_pipeline vs scrapy crawl
import sys
current_dir = os.path.dirname(os.path.abspath(__file__))
simple_script_dir = os.path.join(os.path.dirname(current_dir), 'simple_script')
if simple_script_dir not in sys.path:
    sys.path.append(simple_script_dir)
from proxy_manager import proxy_manager

class BossDetailDrissionSpider(scrapy.Spider):
    name = "boss_detail_drission"
    
    # We do not use Scrapy's request engine for fetching. We use DP inside a loop.
    # Therefore, we override start_requests with a dummy and handle the loop in a background task or in spider_opened.
    custom_settings = {
        # Optional: You can route data through your Scrapy Pipelines
        # "ITEM_PIPELINES": {
        #     "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
        # },
        # We don't really need Scrapy's downloader, but we keep the structure
        "CONCURRENT_REQUESTS": 1,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page = None
        self.current_proxy = None
        self.running = True

    def _get_random_user_agent(self):
        import random
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        ]
        return random.choice(uas)

    def _get_browser(self, proxy_url=None):
        """Configure and launch ChromiumPage"""
        co = ChromiumOptions()
        
        # 1. Randomize Fingerprint on browser restart
        ua = self._get_random_user_agent()
        self.logger.info(f"Setting Fingerprint UA: {ua}")
        co.set_user_agent(ua)
        
        if proxy_url:
            if '@' in proxy_url:
                self.logger.info(f"Setting browser Auth proxy via extension: {proxy_url.split('@')[-1]}")
                plugin_path = self._create_proxy_extension(proxy_url)
                co.add_extension(plugin_path)
            else:
                self.logger.info(f"Setting browser proxy: {proxy_url}")
                co.set_proxy(proxy_url)
        else:
            self.logger.warning("No proxy provided, running with direct connection.")
        
        # Isolate user data to prevent proxy bypass due to existing chrome instances
        user_data_dir = os.path.join(simple_script_dir, "chrome_isolated_data_drission_spider")
        co.set_user_data_path(user_data_dir)
        
        # Efficiency Settings
        #co.set_argument("--blink-settings=imagesEnabled=false") # Disable images
        #co.set_argument("--disable-javascript") # Do NOT disable JS, Boss needs it for anti-bot
        co.set_argument("--ignore-certificate-errors")
        
        # Block annoying trackers/CSS to speed up loading
        co.set_argument("--disable-features=IsolateOrigins,site-per-process")
        
        co.mute(True) # Mute audio
        
        page = ChromiumPage(co)
        # Set page load strategy to 'none' - don't wait for all resources to finish
        page.set.load_mode.none()
        
        return page

    async def start(self):
        """
        Since we are doing full DrissionPage takeover, we yield one dummy request
        and start our custom DP loop in the parse method. 
        Alternatively, we could use signals.spider_opened to start an async loop.
        Using a dummy request is the simplest way to inject into the Scrapy engine.
        """
        # We start the browser
        self.current_proxy = proxy_manager.get_proxy()
        try:
            self.page = self._get_browser(self.current_proxy)
            self.logger.info("Browser initialized successfully.")
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return
            
        yield scrapy.Request('data:,', callback=self.parse_loop, dont_filter=True)

    async def parse_loop(self, response):
        """The main loop that controls DrissionPage, fetches tasks from DB, and extracts data"""
        self.logger.info("Starting DrissionPage polling loop...")
        
        while self.running:
            # 1. Fetch a batch of Tasks from DB to reduce query overhead
            jobs = await self._fetch_task_batch(batch_size=1)
            
            if not jobs:
                self.logger.info("No pending tasks. Waiting 5 seconds...")
                await asyncio.sleep(5)
                continue

            # `jobs` is practically a list from SQLAlchemy's .all(), but Pyre2 might struggle
            
            for job in jobs:
                encrypt_job_id = job.encrypt_job_id
                url = f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html"
                self.logger.info(f"Processing Task: {encrypt_job_id} -> {url}")
    
                # 2. Navigate and Anti-Bot Check
                success = await self._navigate_with_anti_bot(url)
                
                if not success:
                   self.logger.warning(f"Failed to navigate properly for {encrypt_job_id}, retrying later.")
                   # Revert task state to pending
                   await self._revert_task(encrypt_job_id)
                   continue
                   
                # 3. Extract Data
                html_content = self.page.html if self.page else ""
                job_desc = self._extract_job_desc(html_content)
                
                if job_desc:
                    # 4. Save to DB
                    await self._update_job_in_db(encrypt_job_id, job_desc)
                    self.logger.info(f"Successfully processed and updated {encrypt_job_id}")
                else:
                    self.logger.warning(f"Could not extract description for {encrypt_job_id}. Layout change?")
                    await self._update_job_in_db(encrypt_job_id, "解析失败: 未找到描述")
    
                # 5. Very short sleep to let DP breathe and prevent instant IP blocks
                await asyncio.sleep(3)

    async def _navigate_with_anti_bot(self, url):
        """Navigate to URL, handle anti-spider blocks, rotate proxy if necessary"""
        try:
            if not self.page:
                self.logger.warning("Browser page is None. Attempting to initialize.")
                self.page = self._get_browser(self.current_proxy)
                if not self.page:
                    return False
                    
            self.page.get(url)
            
            # Dynamic Wait: Instead of fixed sleep, wait up to 3 seconds for the target element or captcha to appear
            # This is the biggest speedup! If it loads in 0.5s, we save 2.5s.
            if getattr(self, 'page', None):
                try:
                    # 'ele_loaded' checks if it's in DOM. Or 'ele_displayed'
                    self.page.wait.ele_loaded('.job-detail-section', timeout=3)
                except Exception:
                    pass # Timeout means it might be blocked or very slow, we check html anyway
            
            html = self.page.html if getattr(self, 'page', None) else ""
            
            # Check for Anti-Bot patterns
            #is_blocked = ("安全拦截" in html or "验证码" in html or "系统检测到您" in html)
            
            # self.page.url might be a property, but it's safe to check
            current_url = self.page.url if getattr(self.page, 'url', None) else ""
            security_urls = ['https://www.zhipin.com/web/user/safe','security']
            is_security_url = any(security_url in current_url for security_url in security_urls)
            #is_blocked or
            if is_security_url:
                
                self.logger.warning("[Anti-Bot] Security block detected! Please solve the Captcha manually.")
                self.logger.warning("[Anti-Bot] You have 60 seconds. Waiting...")
                
                # Pause and poll for user manual solving
                for i in range(20):
                    await asyncio.sleep(3)
                    current_url = self.page.url if getattr(self, 'page', None) else ""
                    if current_url and not any(url in current_url for url in security_urls):
                         self.logger.info("[Anti-Bot] Captcha manually solved! Resuming task.")
                         return True
                         
                self.logger.warning("[Anti-Bot] Captcha timeout. Rotating IP and Fingerprint...")
                
                # Report bad proxy
                proxy_manager.remove_proxy(self.current_proxy)
                
                # Get new proxy
                self.current_proxy = proxy_manager.get_proxy()
                self.logger.warning("[Anti-Bot] Restarting browser with new Proxy and Fingerprint...")
                
                # Restart browser & Try clear cookies for deep reset
                try:
                    if getattr(self, 'page', None):
                        try:
                            self.page.cookies.clear()
                        except: pass
                        self.page.quit()
                except Exception:
                    pass
                
                # Small cooldown before restart
            
                # Update page object
                new_page = self._get_browser(self.current_proxy)
                if new_page:
                    self.page = new_page
                else:
                    self.logger.error("Failed to re-initialize browser.")
                    
                return False # Failed this iteration, needs retry
                
            return True # Success
            
        except Exception as e:
            self.logger.error(f"Browser navigation error: {e}")
            
            # Attempt recovery
            proxy_manager.remove_proxy(self.current_proxy)
            self.current_proxy = proxy_manager.get_proxy()
            try:
                if getattr(self, 'page', None):
                    try:
                        self.page.cookies.clear()
                    except: pass
                    self.page.quit()
            except Exception:
                pass
            
            await asyncio.sleep(2)
            
            new_page = self._get_browser(self.current_proxy)
            if new_page:
                self.page = new_page
            return False

    def _extract_job_desc(self, html_content):
        """Parse HTML to get the job description"""
        try:
            sel = Selector(text=html_content)
            # Exact CSS selector from original spider
            job_desc = sel.css('.job-detail-section > .job-sec-text::text').getall()
            if not job_desc:
                # Fallback or alternative selector if Boss changed layout
                 job_desc = sel.css('.job-detail-section .job-sec-text *::text').getall()
                 
            job_desc = "\n".join([x.strip() for x in job_desc if x.strip()])
            return job_desc
        except Exception as e:
            self.logger.error(f"Extraction error: {e}")
            return None

    def _create_proxy_extension(self, proxy_url):
        """Generate a Chrome extension to handle proxy with authentication"""
        import os
        proxy_url = proxy_url.replace('http://', '').replace('https://', '')
        auth, ip_port = proxy_url.split('@')
        username, password = auth.split(':')
        ip, port = ip_port.split(':')

        plugin_path = os.path.join(simple_script_dir, "proxy_auth_plugin")
        os.makedirs(plugin_path, exist_ok=True)

        manifest_json = """
        {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Chrome Proxy",
            "permissions": [
                "proxy",
                "tabs",
                "unlimitedStorage",
                "storage",
                "<all_urls>",
                "webRequest",
                "webRequestBlocking"
            ],
            "background": {
                "scripts": ["background.js"]
            },
            "minimum_chrome_version":"22.0.0"
        }
        """

        background_js = """
        var config = {
                mode: "fixed_servers",
                rules: {
                  singleProxy: {
                    scheme: "http",
                    host: "%s",
                    port: parseInt(%s)
                  },
                  bypassList: ["localhost"]
                }
              };

        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

        function callbackFn(details) {
            return {
                authCredentials: {
                    username: "%s",
                    password: "%s"
                }
            };
        }

        chrome.webRequest.onAuthRequired.addListener(
                    callbackFn,
                    {urls: ["<all_urls>"]},
                    ['blocking']
        );
        """ % (ip, port, username, password)

        with open(os.path.join(plugin_path, "manifest.json"), "w", encoding='utf-8') as f:
            f.write(manifest_json.strip())
        with open(os.path.join(plugin_path, "background.js"), "w", encoding='utf-8') as f:
            f.write(background_js.strip())
            
        return plugin_path

    async def _fetch_task_batch(self, batch_size=5):
        """Fetch multiple pending jobs from DB to save query time"""
        try:
            session = await db_manager.get_session()
            async with session:
                stmt = select(Job).where(
                    (Job.is_crawl == 0) & 
                    (Job.encrypt_job_id != None) & 
                    (Job.encrypt_job_id != '')
                ).limit(batch_size).order_by(Job.id.asc())
                
                result = await session.execute(stmt)
                jobs = result.scalars().all()
                
                if jobs:
                    # Mark all as processing (2)
                    for job in jobs:
                        job.is_crawl = 2 
                        job.updated_at = datetime.now()
                    await session.commit()
                    return jobs
                return []
        except Exception as e:
            self.logger.error(f"Error fetching task batch: {e}")
            return []

    async def _revert_task(self, encrypt_job_id):
         """Revert task state back to pending (0) if navigation failed"""
         try:
            session = await db_manager.get_session()
            async with session:
                stmt = select(Job).where(Job.encrypt_job_id == encrypt_job_id)
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                if job:
                     job.is_crawl = 0
                     await session.commit()
         except Exception as e:
             self.logger.error(f"Error reverting task: {e}")

    async def _update_job_in_db(self, encrypt_job_id, job_desc):
        """Update job with the crawled description"""
        try:
            session = await db_manager.get_session()
            async with session:
                stmt = select(Job).where(Job.encrypt_job_id == encrypt_job_id)
                result = await session.execute(stmt)
                job = result.scalar_one_or_none()
                
                if job:
                    job.description = job_desc
                    job.is_crawl = 1 # Finished
                    job.updated_at = datetime.now()
                    await session.commit()
                    return True
                else:
                    self.logger.warning(f"Job {encrypt_job_id} not found in DB during update")
                    return False
        except Exception as e:
            self.logger.error(f"DB Update Error: {e}")
            return False

    def close(self, reason):
        """Cleanup browser on spider close"""
        self.running = False
        try:
            if getattr(self, 'page', None):
                self.page.quit()
                self.logger.info("Browser closed successfully.")
        except Exception as e:
             self.logger.error(f"Error closing browser: {e}")
        super().close(self, reason)
