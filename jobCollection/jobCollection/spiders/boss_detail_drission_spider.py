import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime

import scrapy
from scrapy import Selector
from scrapy import signals
from scrapy.exceptions import DontCloseSpider
from sqlalchemy import select

from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from DrissionPage import ChromiumPage, ChromiumOptions

current_dir = os.path.dirname(os.path.abspath(__file__))
simple_script_dir = os.path.join(os.path.dirname(current_dir), "simple_script")
if simple_script_dir not in sys.path:
    sys.path.append(simple_script_dir)
from proxy_manager import proxy_manager


class BossDetailDrissionSpider(scrapy.Spider):
    """
    详情页抓取爬虫（无需登录）。
    - 从 DB 拉取 is_crawl=0 的 job，访问详情页解析描述后写回 DB。
    - 所有参数均可通过环境变量配置。
    """

    name = "boss_detail_drission"
    allowed_domains = ["zhipin.com"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_TIMEOUT": 1800,
        "ITEM_PIPELINES": {},               # 详情页不走 item pipeline，直接写 DB
        "LOG_FILE": f"static/log/scrapy-boss_detail-{datetime.now().strftime('%Y-%m-%d')}.log",
    }

    # ── 可配置参数 ────────────────────────────────────────────────────────
    # 每次抓取完成后随机等待范围（秒）
    REQ_DELAY_MIN       = float(os.getenv("BOSS_DETAIL_DELAY_MIN",         "2.0"))
    REQ_DELAY_MAX       = float(os.getenv("BOSS_DETAIL_DELAY_MAX",         "5.0"))
    # 等待目标元素加载超时（秒）
    LOAD_WAIT_TIMEOUT   = float(os.getenv("BOSS_DETAIL_LOAD_WAIT",         "5.0"))
    # 无任务时等待时间（秒）
    IDLE_WAIT           = float(os.getenv("BOSS_DETAIL_IDLE_WAIT",         "10.0"))
    # 人工解验证码等待周期数 & 每周期秒数
    CAPTCHA_POLL_CYCLES = int(os.getenv("BOSS_DETAIL_CAPTCHA_CYCLES",      "10"))
    CAPTCHA_POLL_SEC    = float(os.getenv("BOSS_DETAIL_CAPTCHA_POLL_SEC",  "6.0"))
    # 代理：请求数触发轮换
    PROXY_ROTATE_REQS   = int(os.getenv("BOSS_DETAIL_PROXY_ROTATE_REQS",  "200"))
    # 代理：时间触发轮换（秒）
    PROXY_ROTATE_SECS   = int(os.getenv("BOSS_DETAIL_PROXY_ROTATE_SECS",  "360"))
    # 指纹：请求数触发轮换
    FP_ROTATE_REQS      = int(os.getenv("BOSS_DETAIL_FP_ROTATE_REQS",     "250"))
    # 每次请求前额外随机 jitter（秒），模拟人工停顿
    JITTER_MIN          = float(os.getenv("BOSS_DETAIL_JITTER_MIN",        "0.5"))
    JITTER_MAX          = float(os.getenv("BOSS_DETAIL_JITTER_MAX",        "2.0"))
    # DB 每批拉取的 job 数
    TASK_BATCH_SIZE     = int(os.getenv("BOSS_DETAIL_TASK_BATCH",          "1"))

    # ── 浏览器分辨率 / 语言候选池 ─────────────────────────────────────────
    _RESOLUTIONS = [(1920, 1080), (1366, 768), (1440, 900), (1536, 864), (1280, 800)]
    _LANGUAGES   = ["zh-CN,zh;q=0.9,en;q=0.8", "zh-CN,zh;q=0.9",
                    "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7"]
    _WEBGL_VENDORS = ["Google Inc. (NVIDIA)", "Google Inc. (AMD)"]
    _WEBGL_RENDERERS = [
        "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "ANGLE (AMD, AMD Radeon Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
    ]
    CUSTOM_USER_AGENTS = [
    # Windows Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Windows Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    ]

    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider._spider_idle, signal=signals.spider_idle)
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page: ChromiumPage | None = None
        self.current_proxy: str | None = None
        self.proxy_start_time: float = 0.0
        self.req_count: int = 0       # 当前代理请求计数
        self.fp_count: int = 0        # 当前指纹请求计数
        # 每抓取 N 页后自动保存一次 Cookie
        self.cookie_save_every = int(float(os.getenv("BOSS_DETAIL_COOKIE_SAVE_EVERY", "100")))
        self._pages_since_cookie_save: int = 0

    # ------------------------------------------------------------------ #
    #  Scrapy 入口
    # ------------------------------------------------------------------ #

    async def start(self):
        await db_manager.initialize()
        await self._init_browser()
        yield scrapy.Request("data:,started", callback=self._parse_loop, dont_filter=True)

    async def _parse_loop(self, response):
        while True:
            jobs = await self._fetch_tasks()
            if not jobs:
                self.logger.info(f"无待处理任务，等待 {self.IDLE_WAIT}s ...")
                await asyncio.sleep(self.IDLE_WAIT)
                continue

            for job in jobs:
                await self._process_job(job)

            # 代理 / 指纹轮换检查
            await self._maybe_rotate()

    def _spider_idle(self, spider):
        self.crawler.engine.crawl(
            scrapy.Request("data:,idle", callback=self._parse_loop, dont_filter=True),
            spider,
        )
        raise DontCloseSpider

    def close(self, reason):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  单条 Job 处理
    # ------------------------------------------------------------------ #

    async def _process_job(self, job):
        encrypt_job_id = job.encrypt_job_id
        url = f"https://www.zhipin.com/job_detail/{encrypt_job_id}.html"
        self.logger.info(f"抓取详情: {encrypt_job_id} → {url}")

        # 随机 jitter，模拟人工间隔
        await asyncio.sleep(random.uniform(self.JITTER_MIN, self.JITTER_MAX))

        success = await self._navigate(url)
        if not success:
            self.logger.warning(f"导航失败，回退任务: {encrypt_job_id}")
            await self._revert_task(encrypt_job_id)
            return

        html = self.page.html if self.page else ""
        job_desc = self._extract_job_desc(html)

        if job_desc:
            await self._update_job(encrypt_job_id, job_desc, success=True)
            self.logger.info(f"详情写入成功: {encrypt_job_id}（{len(job_desc)} 字符）")
        else:
            self.logger.warning(f"描述解析失败: {encrypt_job_id}")
            await self._update_job(encrypt_job_id, None, success=False)

        self.req_count += 1
        self.fp_count += 1

        # 定期保存 Cookie
        self._pages_since_cookie_save += 1
        if self._pages_since_cookie_save >= self.cookie_save_every:
            self._pages_since_cookie_save = 0
            self._save_cookies_to_disk()

        # 请求间随机等待
        await asyncio.sleep(random.uniform(self.REQ_DELAY_MIN, self.REQ_DELAY_MAX))

    # ------------------------------------------------------------------ #
    #  浏览器导航 & 反爬处理
    # ------------------------------------------------------------------ #

    async def _navigate(self, url: str) -> bool:
        if not self.page:
            await self._init_browser()
            if not self.page:
                return False
        try:
            self.page.get(url)

            # 等待目标元素，超时则继续（页面可能已加载）
            try:
                self.page.wait.ele_loaded(".job-detail-section", timeout=self.LOAD_WAIT_TIMEOUT)
            except Exception:
                pass

            current_url = getattr(self.page, "url", "") or ""

            # 检测安全拦截
            if "user/safe" in current_url or "captcha" in current_url:
                return await self._handle_captcha()

            return True

        except Exception as e:
            self.logger.error(f"导航异常: {e}")
            await self._rebuild_browser()
            return False

    async def _handle_captcha(self) -> bool:
        """检测到验证码，等待人工处理"""
        self.logger.warning("⚠️ 检测到安全拦截！请在浏览器中手动完成验证（等待中...）")
        for i in range(self.CAPTCHA_POLL_CYCLES):
            await asyncio.sleep(self.CAPTCHA_POLL_SEC)
            current_url = getattr(self.page, "url", "") or ""
            if "user/safe" not in current_url and "captcha" not in current_url:
                self.logger.info(f"✅ 验证完成，已等待 {(i+1)*self.CAPTCHA_POLL_SEC:.0f}s")
                return True
            self.logger.info(f"等待验证... {(i+1)*self.CAPTCHA_POLL_SEC:.0f}s / {self.CAPTCHA_POLL_CYCLES*self.CAPTCHA_POLL_SEC:.0f}s")

        self.logger.warning("验证超时，轮换代理并重建浏览器")
        if self.current_proxy:
            proxy_manager.remove_proxy(self.current_proxy)
        await self._rebuild_browser()
        return False

    # ------------------------------------------------------------------ #
    #  浏览器初始化 & 轮换
    # ------------------------------------------------------------------ #

    def _make_fingerprint(self) -> dict:
        # try:
        #     from fake_useragent import UserAgent
        #     # 修改处：os 参数传入列表
        #     ua = UserAgent(os=["windows"], browsers=["chrome", "edge"]).random
        # except Exception:
        #     ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        #           "AppleWebKit/537.36 (KHTML, like Gecko) "
        #           "Chrome/122.0.0.0 Safari/537.36")
        
        # 确保从列表中随机选择
        res = random.choice(self._RESOLUTIONS)
        w, h = res[0], res[1]
        
        return {
            "ua": random.choice(self.CUSTOM_USER_AGENTS),
            "width": w,
            "height": h,
            "lang": random.choice(self._LANGUAGES),
            "hw_concurrency": random.choice([4, 8, 12, 16]),
            "device_memory": random.choice([4, 8, 16, 32]),
            "webgl_vendor": random.choice(self._WEBGL_VENDORS),
            "webgl_renderer": random.choice(self._WEBGL_RENDERERS),
        }

    def _build_browser(self, proxy_url: str | None = None) -> ChromiumPage:
        # 1. 生成指纹
        fp = self._make_fingerprint()
        ua = fp["ua"] # Use the UA generated as part of the fingerprint

        co = ChromiumOptions()
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            free_port = s.getsockname()[1]
        co.set_address(f'127.0.0.1:{free_port}')
        
        co.set_user_agent(ua)
        co.set_argument(f"--lang={fp['lang']}")
        co.set_argument(f"--window-size={fp['width']},{fp['height']}")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--disable-infobars")
        co.set_argument("--hide-scrollbars")
        co.set_argument("--enforce-webrtc-ip-permission-check")
        co.set_argument("--force-webrtc-ip-handling-policy=disable-non-proxied-udp")
        co.set_argument("--disable-features=IsolateOrigins,site-per-process")
        co.mute(True)

        # 3. 代理设置
        if proxy_url:
            try:
                if "@" in proxy_url:
                    # 认证代理 (使用专用目录隔离)
                    co.add_extension(self._create_proxy_extension(proxy_url))
                    self.logger.info(f"使用认证代理: {proxy_url.split('@')[-1]}")
                else:
                    # 普通代理
                    co.set_proxy(proxy_url)
                    self.logger.info(f"使用代理: {proxy_url}")
            except Exception as e:
                self.logger.error(f"设置代理失败: {e}")
        else:
            self.logger.warning("代理池为空，使用直连")

        # 4. 隔离数据目录
        user_data_dir = os.path.join(simple_script_dir, "chrome_detail_data")
        co.set_user_data_path(user_data_dir)

        # 5. 创建页面
        page = ChromiumPage(co)
        page.set.load_mode.none()

        # 6. 注入反检测 JS
        stealth_js = f"""
        Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
        window.navigator.chrome = {{runtime: {{}}}};
        const _getP = WebGLRenderingContext.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(p) {{
            if (p === 37445) return '{fp["webgl_vendor"]}';
            if (p === 37446) return '{fp["webgl_renderer"]}';
            return _getP(p);
        }};
        Object.defineProperty(navigator, 'hardwareConcurrency', {{get: () => {fp["hw_concurrency"]}}});
        Object.defineProperty(navigator, 'deviceMemory', {{get: () => {fp["device_memory"]}}});
        """
        page.run_cdp("Page.addScriptToEvaluateOnNewDocument", source=stealth_js)
        self.logger.info(f"浏览器已创建 UA={ua[:40]}... 分辨率={fp['width']}x{fp['height']}")
        return page


    async def _init_browser(self):
        self.current_proxy = proxy_manager.get_proxy()
        self.proxy_start_time = time.time()
        try:
            self.page = self._build_browser(self.current_proxy)
            # 尝试从磁盘加载并注入已保存的 Cookie
            self._load_and_inject_cookies()
        except Exception as e:
            import traceback
            self.logger.error(f"浏览器初始化失败: {traceback.format_exc()}")
            self.page = None

    async def _rebuild_browser(self):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass
        await asyncio.sleep(2)
        await self._init_browser()

    async def _maybe_rotate(self):
        """按请求数或时间，自动轮换代理/指纹"""
        time_elapsed = time.time() - self.proxy_start_time
        need_proxy_rotate = (
            self.req_count >= self.PROXY_ROTATE_REQS
            or time_elapsed >= self.PROXY_ROTATE_SECS
        )
        need_fp_rotate = self.fp_count >= self.FP_ROTATE_REQS

        if need_fp_rotate or need_proxy_rotate:
            reason = "指纹" if need_fp_rotate else "代理"
            self.logger.info(f"[轮换] {reason}触发，重建浏览器（reqs={self.req_count}, elapsed={time_elapsed:.0f}s）")
            if self.current_proxy:
                proxy_manager.remove_proxy(self.current_proxy)
            await self._rebuild_browser()
            self.req_count = 0
            self.fp_count = 0

    # ------------------------------------------------------------------ #
    #  数据解析
    # ------------------------------------------------------------------ #

    def _extract_job_desc(self, html: str) -> str | None:
        try:
            sel = Selector(text=html)
            parts = sel.css(".job-detail-section > .job-sec-text::text").getall()
            if not parts:
                parts = sel.css(".job-detail-section .job-sec-text *::text").getall()
            text = "\n".join(x.strip() for x in parts if x.strip())
            return text or None
        except Exception as e:
            self.logger.error(f"解析异常: {e}")
            return None

    # ------------------------------------------------------------------ #
    #  数据库操作
    # ------------------------------------------------------------------ #

    async def _fetch_tasks(self) -> list:
        try:
            async with (await db_manager.get_session()) as session:
                stmt = (
                    select(Job)
                    .where(
                        (Job.is_crawl == 0)
                        & (Job.encrypt_job_id.isnot(None))
                        & (Job.encrypt_job_id != "")
                        & (Job.major_name.isnot(None))
                        & (Job.major_name != "")
                    )
                    .order_by(Job.id.asc())
                    .limit(self.TASK_BATCH_SIZE)
                )
                result = await session.execute(stmt)
                jobs = result.scalars().all()
                if jobs:
                    for job in jobs:
                        job.is_crawl = 2          # 处理中
                        job.updated_at = datetime.now()
                    await session.commit()
                return list(jobs)
        except Exception as e:
            self.logger.error(f"拉取任务失败: {e}")
            return []

    async def _revert_task(self, encrypt_job_id: str):
        try:
            async with (await db_manager.get_session()) as session:
                result = await session.execute(
                    select(Job).where(Job.encrypt_job_id == encrypt_job_id)
                )
                job = result.scalar_one_or_none()
                if job:
                    job.is_crawl = 0
                    await session.commit()
        except Exception as e:
            self.logger.error(f"回退任务失败: {e}")

    async def _update_job(self, encrypt_job_id: str, job_desc: str | None, success: bool):
        try:
            async with (await db_manager.get_session()) as session:
                result = await session.execute(
                    select(Job).where(Job.encrypt_job_id == encrypt_job_id)
                )
                job = result.scalar_one_or_none()
                if not job:
                    self.logger.warning(f"Job {encrypt_job_id} 不存在于 DB")
                    return
                if success and job_desc:
                    job.description = job_desc
                    job.is_crawl = 1
                else:
                    job.is_crawl = 0       # 解析失败，允许重试
                job.updated_at = datetime.now()
                await session.commit()
        except Exception as e:
            self.logger.error(f"DB 更新失败: {e}")

    # ------------------------------------------------------------------ #
    #  Cookie 持久化
    # ------------------------------------------------------------------ #

    def _cookie_file_path(self,file_path:str="cookies_detail.json") -> str:
        return os.path.join(simple_script_dir, file_path)

    def _save_cookies_to_disk(self):
        """将当前浏览器 Cookie 保存到磁盘。"""
        if not self.page:
            return
        try:
            cookies = self.page.cookies()
            if not cookies:
                return
            path = self._cookie_file_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Cookie 已保存（{len(cookies)} 条）→ {path}")
        except Exception as e:
            self.logger.warning(f"保存 Cookie 失败: {e}")

    def _load_and_inject_cookies(self):
        """从磁盘加载 Cookie 并注入浏览器。"""
        if not self.page:
            return
        path = self._cookie_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            if not isinstance(cookies, list) or not cookies:
                return
            # 先访问一次目标域名，确保 Cookie 能写入
            self.page.set.load_mode.normal()
            self.page.get("https://www.zhipin.com/")
            self.page.set.cookies(cookies)
            self.page.set.load_mode.none()
            self.logger.info(f"已从磁盘注入 Cookie（{len(cookies)} 条）← {path}")
        except Exception as e:
            self.logger.warning(f"加载 Cookie 失败: {e}")

    # ------------------------------------------------------------------ #
    #  代理扩展工具
    # ------------------------------------------------------------------ #

    def _create_proxy_extension(self, proxy_url: str) -> str:
        """为带认证的代理创建 Chrome 扩展插件。"""
        # 去掉协议
        url_clean = proxy_url.replace("http://", "").replace("https://", "")
        
        # 1. 拆分 auth 和 addr
        if "@" in url_clean:
            auth_part, addr_part = url_clean.split("@", 1)
        else:
            auth_part, addr_part = "", url_clean

        # 2. 拆分 user:pass
        if ":" in auth_part:
            username, password = auth_part.split(":", 1)
        else:
            username, password = auth_part, ""

        # 3. 拆分 ip:port
        if ":" in addr_part:
            ip, port = addr_part.split(":", 1)
        else:
            ip, port = addr_part, "80"

        # 使用专用的插件目录，避免与 list 爬虫冲突
        plugin_path = os.path.join(simple_script_dir, "proxy_auth_plugin_detail")
        os.makedirs(plugin_path, exist_ok=True)

        manifest_json = """{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Chrome Proxy Detail",
    "permissions": ["proxy","tabs","unlimitedStorage","storage","<all_urls>","webRequest","webRequestBlocking"],
    "background": {"scripts": ["background.js"]},
    "minimum_chrome_version": "22.0.0"
}"""
        background_js = """var config = {
    mode: "fixed_servers",
    rules: { singleProxy: { scheme: "http", host: "%s", port: parseInt(%s) }, bypassList: ["localhost"] }
};
chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
function callbackFn(details) {
    return { authCredentials: { username: "%s", password: "%s" } };
}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {urls: ["<all_urls>"]}, ["blocking"]);
""" % (ip, port, username, password)

        with open(os.path.join(plugin_path, "manifest.json"), "w", encoding="utf-8") as f:
            f.write(manifest_json)
        with open(os.path.join(plugin_path, "background.js"), "w", encoding="utf-8") as f:
            f.write(background_js)

        return plugin_path


    def _format_proxy(self, proxy_url: str) -> str | None:
        """格式化代理地址为正确格式"""
        if not proxy_url:
            return None
        
        # 如果已经是完整格式
        if proxy_url.startswith(('http://', 'https://', 'socks5://')):
            return proxy_url
        
        # 如果是 ip:port 格式
        if ':' in proxy_url and proxy_url.count(':') == 1:
            # 检查是否是有效的IP:端口
            parts = proxy_url.split(':')
            if parts[0].replace('.', '').isdigit() and parts[1].isdigit():
                return f'http://{proxy_url}'
        
        # 如果只是端口号
        if proxy_url.isdigit():
            self.logger.warning(f"代理只有端口号: {proxy_url}，使用默认IP 127.0.0.1")
            return f'http://127.0.0.1:{proxy_url}'
        
        # 其他格式，可能有问题
        self.logger.warning(f"无法识别的代理格式: {proxy_url}")
        return None