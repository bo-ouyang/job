import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Optional

import scrapy
from scrapy import signals
from scrapy.exceptions import DontCloseSpider
from sqlalchemy import select

from common.databases.PostgresManager import db_manager
from common.databases.models.job import Job
from DrissionPage import ChromiumPage, ChromiumOptions
from jobCollection.boss.parsers import parse_job_description
from jobCollection.boss.proxy import (
    cleanup_proxy_auth_extension,
    create_proxy_auth_extension,
    proxy_manager,
)
from jobCollection.items.boss_job_item import BossJobDetailItem

current_dir = os.path.dirname(os.path.abspath(__file__))
simple_script_dir = os.path.join(os.path.dirname(current_dir), "simple_script")


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
        "CONCURRENT_ITEMS": 1,
        "DOWNLOAD_TIMEOUT": 1800,
        "ITEM_PIPELINES": {
            "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
        },
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

    def __init__(self, account_index: str = "1", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_index = str(account_index)
        self.page: Optional[ChromiumPage] = None
        self.proxy_extension_path: Optional[str] = None
        self.current_proxy: Optional[str] = None
        self.proxy_start_time: float = 0.0
        self.req_count: int = 0       # 当前代理请求计数
        self.fp_count: int = 0        # 当前指纹请求计数
        # 每抓取 N 页后自动保存一次 Cookie
        self.cookie_save_every = int(float(os.getenv("BOSS_DETAIL_COOKIE_SAVE_EVERY", "100")))
        self._pages_since_cookie_save: int = 0

    # ------------------------------------------------------------------ #
    #  Scrapy 入口
    # ------------------------------------------------------------------ #

    def _bootstrap_request(self):
        return scrapy.Request(
            "data:,bootstrap", callback=self._bootstrap, dont_filter=True
        )

    def start_requests(self):
        yield self._bootstrap_request()

    async def start(self):
        yield self._bootstrap_request()

    async def _bootstrap(self, response):
        await db_manager.initialize()
        await self._init_browser()
        yield scrapy.Request("data:,loop", callback=self._parse_loop, dont_filter=True)

    async def _parse_loop(self, response):
        jobs = await self._fetch_tasks()
        if not jobs:
            self.logger.info(f"无待处理任务，等待 {self.IDLE_WAIT}s ...")
            await asyncio.sleep(self.IDLE_WAIT)
        else:
            for job in jobs:
                item = await self._process_job(job)
                if item is not None:
                    yield item
            await self._maybe_rotate()
        yield scrapy.Request("data:,loop", callback=self._parse_loop, dont_filter=True)

    def _spider_idle(self, spider):
        self.crawler.engine.crawl(
            scrapy.Request("data:,idle", callback=self._parse_loop, dont_filter=True)
        )
        raise DontCloseSpider

    def close(self, reason):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass
        self._cleanup_proxy_extension()

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
        job_desc = parse_job_description(html)

        if job_desc:
            self.logger.info(f"详情写入成功: {encrypt_job_id}（{len(job_desc)} 字符）")
        else:
            self.logger.warning(f"描述解析失败: {encrypt_job_id}")
            await self._revert_task(encrypt_job_id)
            return None

        self.req_count += 1
        self.fp_count += 1

        # 定期保存 Cookie
        self._pages_since_cookie_save += 1
        if self._pages_since_cookie_save >= self.cookie_save_every:
            self._pages_since_cookie_save = 0
            self._save_cookies_to_disk()

        # 请求间随机等待
        await asyncio.sleep(random.uniform(self.REQ_DELAY_MIN, self.REQ_DELAY_MAX))
        return BossJobDetailItem(
            encrypt_job_id=encrypt_job_id,
            job_desc=job_desc,
        )

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
                self.page.wait.eles_loaded(
                    ".job-detail-section", timeout=self.LOAD_WAIT_TIMEOUT
                )
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

    def _cleanup_proxy_extension(self):
        cleanup_proxy_auth_extension(self.proxy_extension_path)
        self.proxy_extension_path = None

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

    def _build_browser(self, proxy_url: Optional[str] = None) -> ChromiumPage:
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
                    self.proxy_extension_path = create_proxy_auth_extension(
                        proxy_url,
                        simple_script_dir,
                        f"detail_{self.account_index}",
                    )
                    co.add_extension(self.proxy_extension_path)
                    self.logger.info(f"使用认证代理: {proxy_url.split('@')[-1]}")
                else:
                    # 普通代理
                    co.set_proxy(proxy_url)
                    self.logger.info(f"使用代理: {proxy_url}")
            except Exception as e:
                self.logger.error(f"设置代理失败: {e}")
        else:
            self.logger.warning("代理池为空，使用直连")

        # 4. 隔离数据目录(避免多个终端并发报错锁文件)
        user_data_dir = os.path.join(simple_script_dir, f"chrome_detail_data_{self.account_index}")
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
        self.current_proxy = await asyncio.to_thread(proxy_manager.get_proxy)
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
        self._cleanup_proxy_extension()
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
                    )
                    .order_by(Job.id.asc())
                    .limit(self.TASK_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
                async with session.begin():
                    result = await session.execute(stmt)
                    jobs = result.scalars().all()
                    for job in jobs:
                        job.is_crawl = 2          # 处理中
                        job.updated_at = datetime.now()
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

    # ------------------------------------------------------------------ #
    #  Cookie 持久化
    # ------------------------------------------------------------------ #

    def _cookie_file_path(self, file_path: str = None) -> str:
        if not file_path:
            file_path = f"cookies_detail_account_{self.account_index}.json"
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
            # 兼容读取 list 爬虫登录并缓存下来的对应的 Cookie
            path = self._cookie_file_path(f'cookies_account_{self.account_index}.json')
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
