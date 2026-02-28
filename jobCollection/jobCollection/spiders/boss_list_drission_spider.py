import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from http.cookies import SimpleCookie
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import scrapy
from scrapy import signals
from scrapy.exceptions import CloseSpider, DontCloseSpider
from sqlalchemy import select, update

from common.databases.PostgresManager import db_manager
from common.databases.models.boss_stu_crawl_url import BossStuCrawlUrl
from jobCollection.items.boss_job_item import BossJobItem

from DrissionPage import ChromiumPage, ChromiumOptions

current_dir = os.path.dirname(os.path.abspath(__file__))
simple_script_dir = os.path.join(os.path.dirname(current_dir), "simple_script")
if simple_script_dir not in sys.path:
    sys.path.append(simple_script_dir)
from proxy_manager import proxy_manager


class BossListDrissionSpider(scrapy.Spider):
    """
    使用 DrissionPage 直接监听/抓取列表数据，不再依赖 mitmproxy + Redis 桥接。

    启动流程：
      1. 打开浏览器
      2. 尝试注入已保存的 Cookie；若未登录则导航到登录页等待手动登录
      3. 登录成功后启用图片屏蔽，然后开始循环抓取任务
    """

    name = "boss_list_drission"
    allowed_domains = ["zhipin.com"]

    custom_settings = {
        "DOWNLOAD_TIMEOUT": 1800,
        "CONCURRENT_REQUESTS": 1,
        "ITEM_PIPELINES": {
            "jobCollection.pipelines.redis_dedup_pipeline.RedisDeduplicationPipeline": 200,
            "jobCollection.pipelines.boss_pipeline.BossJobPipeline": 300,
        },
        "LOG_FILE": f"static/log/scrapy-boss_list-{datetime.now().strftime('%Y-%m-%d')}.log",

    }

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
        return spider

    def __init__(self, task_id: Optional[str] = None, accounts_json: Optional[str] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_task_id = int(task_id) if task_id else None
        self.accounts_json = accounts_json

        self.page: Optional[ChromiumPage] = None
        self.is_checking = False
        self.item_queue: asyncio.Queue = asyncio.Queue()

        # ── 代理配置 ──────────────────────────────────────────────────────
        self.current_proxy: Optional[str] = None
        self.proxy_started_at = 0.0
        self.proxy_rotate_seconds = int(os.getenv("BOSS_PROXY_ROTATE_SECONDS", "360"))

        # ── 账户配置 ──────────────────────────────────────────────────────
        self.accounts = self._load_accounts()
        self.account_index = 0

        # ── 任务状态 ────────────────────────────────────────────────
        self.current_task_id: Optional[int] = None
        self.current_task_url = ""
        self.current_task_major_name = ""  # 来自 BossStuCrawlUrl.major_name
        self.current_task_retry = 0

        # ── 抓取行为参数（可通过环境变量覆盖）────────────────────────────
        # 每页最大重试次数
        self.max_retry_per_page     = int(float(os.getenv("BOSS_MAX_RETRY_PER_PAGE",    "3")))
        # 每页抓取完成后等待时间范围（秒），模拟人工停顿，避免风控
        self.page_delay_min         = float(os.getenv("BOSS_PAGE_DELAY_MIN",            "2.0"))
        self.page_delay_max         = float(os.getenv("BOSS_PAGE_DELAY_MAX",            "5.0"))
        # 滚动次数
        self.scroll_count           = int(float(os.getenv("BOSS_SCROLL_COUNT",          "4")))
        # 每次滚动基准距离（px）
        self.scroll_px              = int(float(os.getenv("BOSS_SCROLL_PX",             "500")))
        # 每次滚动距离随机浮动范围（±px）
        self.scroll_px_jitter       = int(float(os.getenv("BOSS_SCROLL_PX_JITTER",      "100")))
        # 页面初始渲染等待时间范围（秒）
        self.scroll_init_wait_min   = float(os.getenv("BOSS_SCROLL_INIT_WAIT_MIN",      "1.0"))
        self.scroll_init_wait_max   = float(os.getenv("BOSS_SCROLL_INIT_WAIT_MAX",      "2.0"))
        # 每次滚动之间等待时间范围（秒）
        self.scroll_interval_min    = float(os.getenv("BOSS_SCROLL_INTERVAL_MIN",       "0.5"))
        self.scroll_interval_max    = float(os.getenv("BOSS_SCROLL_INTERVAL_MAX",       "1.5"))
        # 登录等待轮询间隔（秒）
        self.login_poll_interval    = float(os.getenv("BOSS_LOGIN_POLL_INTERVAL",       "5.0"))
        # 登录等待最长时间（秒）
        self.login_timeout          = float(os.getenv("BOSS_LOGIN_TIMEOUT",             "300.0"))
        # 网络数据包监听超时（秒）
        self.listen_timeout         = float(os.getenv("BOSS_LISTEN_TIMEOUT",            "15.0"))
        # 每抓取 N 页后自动保存一次 Cookie
        self.cookie_save_every_pages = int(float(os.getenv("BOSS_COOKIE_SAVE_EVERY_PAGES", "100")))
        self._pages_since_cookie_save = 0  # 计数器

        self.logger.info(
            f"初始化完成，账户数: {len(self.accounts)}，"
            f"页延迟: {self.page_delay_min}-{self.page_delay_max}s，"
            f"代理轮换: {self.proxy_rotate_seconds}s"
        )

    # ------------------------------------------------------------------ #
    #  Scrapy 入口
    # ------------------------------------------------------------------ #

    async def start(self):
        await db_manager.initialize()
        await self._rebuild_browser()   # 打开浏览器 + 登录验证
        yield scrapy.Request("data:,started", callback=self.parse_loop, dont_filter=True)

    async def parse_loop(self, response):
        while not self.item_queue.empty():
            item = await self.item_queue.get()
            yield item

        if not self.is_checking:
            self.is_checking = True
            try:
                await self._ensure_task_and_process_one_page()
            except CloseSpider:
                raise
            except Exception as e:
                self.logger.error(f"循环处理异常: {e}")
            finally:
                self.is_checking = False

        await asyncio.sleep(0.2)
        yield scrapy.Request("data:,loop", callback=self.parse_loop, dont_filter=True)

    def spider_idle(self, spider):
        self.crawler.engine.crawl(
            scrapy.Request("data:,idle", callback=self.parse_loop, dont_filter=True),
            spider,
        )
        raise DontCloseSpider

    async def spider_closed(self, spider):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  任务调度
    # ------------------------------------------------------------------ #

    async def _ensure_task_and_process_one_page(self):
        await self._check_proxy_rotation()

        if self.current_task_id is None:
            await self._fetch_and_assign_new_task()
            return

        if not await self._sync_db_status():
            return

        await self._process_current_page()

    async def _process_current_page(self):
        """
        抓取当前任务的全部数据：导航一次，每轮监听到 job/list.json 立即入库。
        """
        self.logger.info(
            f"处理任务 {self.current_task_id} [{self.current_task_major_name}]: {self.current_task_url}"
        )
        total_count, success = await self._fetch_all_by_scroll(self.current_task_url)

        if not success:
            self.current_task_retry += 1
            self.logger.warning(
                f"任务 {self.current_task_id} 抓取失败，"
                f"重试 {self.current_task_retry}/{self.max_retry_per_page}"
            )
            await self._handle_page_failure()
            return

        self.current_task_retry = 0

        # 定期保存 Cookie
        self._pages_since_cookie_save += 1
        if self._pages_since_cookie_save >= self.cookie_save_every_pages:
            self._pages_since_cookie_save = 0
            await self._save_cookies_to_disk()

        await self._update_db_status(self.current_task_id, "done")
        self.logger.info(f"任务 {self.current_task_id} 完成，共入库 {total_count} 条")
        self.current_task_id = None
        self.current_task_url = ""
        self.current_task_major_name = ""

    async def _handle_page_failure(self):
        await self._rotate_proxy_and_browser()

        if self.current_task_retry <= self.max_retry_per_page:
            return

        if self.current_task_id:
            await self._update_db_status(self.current_task_id, "error", error_msg="列表页抓取连续失败")
        self.current_task_id = None
        self.current_task_url = ""
        self.current_task_major_name = ""
        self.current_task_retry = 0

    # ------------------------------------------------------------------ #
    #  数据抓取
    # ------------------------------------------------------------------ #

    async def _fetch_all_by_scroll(
        self, url: str
    ) -> Tuple[int, bool]:
        """
        导航到 url（仅一次），循环：滚动 -> 等待 job/list.json 包 -> 立即入库
        直到 has_more=False 或达到最大页数。返回 (total_count, success)。
        """
        if not self.page:
            await self._rebuild_browser()
            if not self.page:
                return 0, False

        max_pages = int(os.getenv("BOSS_MAX_PAGES_PER_TASK", "10"))
        total_count = 0

        try:
            listen_ready = hasattr(self.page, "listen") and hasattr(self.page.listen, "start")
            if listen_ready:
                self.page.listen.start(["job/list.json", "joblist.json"])

            # 仅导航一次
            self.page.get(url)

            current_url = getattr(self.page, "url", "") or ""
            if any(sig in current_url for sig in ["user/safe", "captcha", "login"]):
                self.logger.warning(f"检测到拦截页面: {current_url}，重建浏览器")
                await self._rebuild_browser()
                return 0, False

            for page_num in range(1, max_pages + 1):
                # 滚动触发懒加载
                await self._scroll_to_load()

                # 等待网络包
                payload: Optional[Dict[str, Any]] = None
                if listen_ready:
                    packet = self.page.listen.wait(timeout=self.listen_timeout)
                    payload = self._extract_payload_from_packet(packet)

                # 兜底：JS 直接请求 API
                if payload is None:
                    payload = self._fetch_job_list_by_js(url)

                if payload is None:
                    self.logger.warning(f"第 {page_num} 轮未获取到数据，结束循环")
                    break

                jobs, has_more = self._extract_jobs_and_has_more(payload)

                # 立即入库，不等所有轮次结束
                if jobs:
                    await self._emit_job_items(url, jobs, self.current_task_major_name)
                    total_count += len(jobs)

                self.logger.info(
                    f"第 {page_num} 轮抓取 {len(jobs)} 条入库，has_more={has_more}，累计 {total_count} 条"
                )

                if not has_more:
                    break

                # 轮次间随机等待，模拟人工操作
                await asyncio.sleep(random.uniform(self.page_delay_min, self.page_delay_max))

            return total_count, True

        except Exception as e:
            self.logger.error(f"滚动抓取异常: {e}")
            return 0, False

    async def _scroll_to_load(self):
        """模拟人工滚动（随机停顿），触发 BOSS 直聘列表页懒加载 API 请求。"""
        if not self.page:
            return
        await asyncio.sleep(random.uniform(self.scroll_init_wait_min, self.scroll_init_wait_max))
        try:
            for i in range(self.scroll_count):
                px = self.scroll_px + random.randint(-self.scroll_px_jitter, self.scroll_px_jitter)
                self.page.scroll.down(px)
                await asyncio.sleep(random.uniform(self.scroll_interval_min, self.scroll_interval_max))
        except Exception as e:
            self.logger.warning(f"页面滚动异常（可忽略）: {e}")

    def _fetch_job_list_by_js(self, page_url: str) -> Optional[Dict[str, Any]]:
        """JS fetch 兜底：直接请求 API"""
        if not self.page:
            return None
        api_url = self._build_job_api_url(page_url)
        if not api_url:
            return None
        js = f"""
        return fetch("{api_url}", {{ credentials: "include" }})
            .then(resp => resp.text())
            .catch(err => JSON.stringify({{"__error__": String(err)}}));
        """
        try:
            raw = self.page.run_js(js)
            if not raw:
                return None
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else None
        except Exception as e:
            self.logger.warning(f"JS 拉取兜底失败: {e}")
        return None

    def _build_job_api_url(self, page_url: str) -> Optional[str]:
        parsed = urlparse(page_url)
        query = parse_qs(parsed.query)
        query.setdefault("page", [str(self.current_page)])
        query.setdefault("pageSize", ["30"])
        q = urlencode({k: v[0] for k, v in query.items() if v}, doseq=False)
        return f"https://www.zhipin.com/wapi/zpgeek/search/joblist.json?{q}"

    def _extract_payload_from_packet(self, packet: Any) -> Optional[Dict[str, Any]]:
        if packet is None:
            return None
        for path in (("response", "body"), ("response", "json"), ("response", "text"), ("body",), ("data",)):
            cur = packet
            for key in path:
                cur = cur.get(key) if isinstance(cur, dict) else getattr(cur, key, None)
                if cur is None:
                    break
            else:
                data = self._normalize_payload(cur)
                if data is not None:
                    return data
        return None

    def _normalize_payload(self, raw: Any) -> Optional[Dict[str, Any]]:
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8", errors="ignore")
            except Exception:
                return None
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return None
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
            except Exception:
                return None
        return None

    def _extract_jobs_and_has_more(self, payload: Optional[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
        if not payload:
            return [], False
        if "zpData" in payload and isinstance(payload["zpData"], dict):
            zp = payload["zpData"]
            return zp.get("jobList") or [], bool(zp.get("hasMore", False))
        data = payload.get("data")
        if isinstance(data, dict):
            return data.get("jobList") or data.get("list") or [], bool(data.get("hasMore", False))
        return payload.get("jobList") or payload.get("list") or [], bool(payload.get("hasMore", False))

    async def _emit_job_items(self, source_url: str, jobs: List[Dict[str, Any]], major_name: str = ""):
        parsed_url = urlparse(source_url)
        query_params = parse_qs(parsed_url.query)
        url_industry = query_params.get("industry", [None])[0]
        url_city = query_params.get("city", [None])[0]

        for job in jobs:
            item = BossJobItem()
            item["job_name"] = job.get("jobName")
            item["salary_desc"] = job.get("salaryDesc")
            item["job_experience"] = job.get("jobExperience")
            item["job_degree"] = job.get("jobDegree")
            item["city_name"] = job.get("cityName")
            item["area_district"] = job.get("areaDistrict")
            item["business_district"] = job.get("businessDistrict")
            item["job_labels"] = job.get("jobLabels", [])
            item["skills"] = job.get("skills", [])
            item["welfare_list"] = job.get("welfareList", [])
            item["encrypt_job_id"] = job.get("encryptJobId")
            item["encrypt_brand_id"] = job.get("encryptBrandId")
            item["brand_name"] = job.get("brandName")
            item["brand_logo"] = job.get("brandLogo")
            item["brand_stage_name"] = job.get("brandStageName")
            item["brand_industry"] = job.get("brandIndustry")
            item["brand_scale_name"] = job.get("brandScaleName")
            item["longitude"] = job.get("gps", {}).get("longitude") if job.get("gps") else None
            item["latitude"] = job.get("gps", {}).get("latitude") if job.get("gps") else None
            item["boss_name"] = job.get("bossName")
            item["boss_title"] = job.get("bossTitle")
            item["boss_avatar"] = job.get("bossAvatar")
            item["major_name"] = major_name or None

            industry_code = url_industry or job.get("industry")
            if industry_code:
                try:
                    item["industry_code"] = int(industry_code)
                except Exception:
                    pass
            if url_city:
                try:
                    item["city_code"] = int(url_city)
                except Exception:
                    pass

            await self.item_queue.put(item)

    # ------------------------------------------------------------------ #
    #  浏览器 & 代理
    # ------------------------------------------------------------------ #

    async def _rebuild_browser(self):
        """关闭旧浏览器，创建新浏览器，完成登录验证后开始抓取。"""
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass

        await asyncio.sleep(1)

        self.current_proxy = proxy_manager.get_proxy()
        self.proxy_started_at = time.time()

        co = ChromiumOptions()
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            free_port = s.getsockname()[1]
        co.set_address(f'127.0.0.1:{free_port}')
        #co.auto_port(True)   # 自动选空闲端口，避免与其他爬虫实例冲突
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_argument("--ignore-certificate-errors")
        co.set_argument("--disable-infobars")
        co.set_argument("--hide-scrollbars")
        # 注意：不在启动时禁用图片，登录页需显示二维码；图片屏蔽在登录后动态启用

        account = self.accounts[self.account_index]
        user_data_dir = account.get("user_data_dir") or os.path.join(
            simple_script_dir, f"chrome_isolated_data_list_{self.account_index + 1}"
        )
        os.makedirs(user_data_dir, exist_ok=True)
        co.set_user_data_path(user_data_dir)

        if self.current_proxy:
            if "@" in self.current_proxy:
                co.add_extension(self._create_proxy_extension(self.current_proxy))
                self.logger.info(f"使用认证代理: {self.current_proxy.split('@')[-1]}")
            else:
                co.set_proxy(self.current_proxy)
                self.logger.info(f"使用代理: {self.current_proxy}")
        else:
            self.logger.warning("代理池为空，使用直连")
        #co.headless(True)
        self.page = ChromiumPage(co)
        self.page.set.load_mode.none()
        self.logger.info("浏览器已创建，开始登录验证...")

        await self._ensure_logged_in()

    async def _ensure_logged_in(self):
        """
        登录保证流程：
        1. 尝试从磁盘加载已保存 Cookie 并注入
        2. 访问首页检查登录状态
        3. 若未登录 → 打开登录页等待手动登录（最长 5 分钟）
        4. 登录成功 → 保存 Cookie 到磁盘 + 启用图片屏蔽
        """
        if not self.page:
            return

        account = self.accounts[self.account_index]
        account_name = account.get("name", f"account-{self.account_index + 1}")

        # Step 1：注入 Cookie（优先磁盘 > 配置）
        cookies = account.get("cookies") or self._load_cookies_from_disk(self.account_index)
        if cookies:
            try:
                self.page.set.load_mode.normal()
                self.page.get("https://www.zhipin.com/")
                self.page.set.cookies(self._parse_cookies(cookies))
                self.page.set.load_mode.none()
                self.logger.info(f"账户 [{account_name}] 已注入 Cookie（{len(cookies) if isinstance(cookies, list) else '?'} 条）")
            except Exception as e:
                self.logger.warning(f"Cookie 注入失败: {e}")

        # Step 2：检查登录状态
        await asyncio.sleep(1)
        try:
            self.page.set.load_mode.normal()
            self.page.get("https://www.zhipin.com/")
            await asyncio.sleep(1.5)
            self.page.set.load_mode.none()
        except Exception:
            pass

        if self._is_logged_in():
            self.logger.info(f"✓ 账户 [{account_name}] 已登录，开始抓取")
            self._block_images()
            return

        # Step 3：未登录 → 等待手动登录
        self.logger.warning(f"✗ 账户 [{account_name}] 未登录，打开登录页等待手动操作...")
        logged_in = await self._wait_for_manual_login(account_name=account_name)
        if not logged_in:
            self.logger.error(f"账户 [{account_name}] 登录超时，爬虫可能无法抓取数据")

    async def _wait_for_manual_login(
        self,
        account_name: str = "",
        poll_interval: Optional[float] = None,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        导航到 BOSS 直聘登录页，每 5 秒轮询一次登录状态。
        登录成功后保存 Cookie 到磁盘并启用图片屏蔽。
        """
        if not self.page:
            return False

        poll_interval = poll_interval if poll_interval is not None else self.login_poll_interval
        timeout = timeout if timeout is not None else self.login_timeout

        label = f"「{account_name}」" if account_name else ""
        self.logger.warning(f"══ 请在浏览器中手动登录 BOSS 直聘 {label} ══")

        try:
            self.page.set.load_mode.normal()
            self.page.get("https://www.zhipin.com/web/user/login")
        except Exception as e:
            self.logger.warning(f"打开登录页失败: {e}")

        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if self._is_logged_in():
                self.logger.info(f"✅ 登录成功！已等待 {elapsed:.0f}s")
                try:
                    self.page.set.load_mode.none()
                except Exception:
                    pass
                self._block_images()
                await self._save_cookies_to_disk()
                return True

            self.logger.info(f"等待登录... {elapsed:.0f}s / {timeout:.0f}s")

        self.logger.error(f"登录等待超时 ({timeout}s)")
        try:
            self.page.set.load_mode.none()
        except Exception:
            pass
        return False

    def _is_logged_in(self) -> bool:
        """
        检查当前页面是否已登录。
        优先 Cookie token 检测，辅以 URL / DOM 检测。
        """
        if not self.page:
            return False
        try:
            url = getattr(self.page, "url", "") or ""
            if any(sig in url for sig in ["login", "user/safe", "captcha", "/passport"]):
                return False

            # Cookie 检测：BOSS 直聘认证 token
            try:
                cookies = self.page.cookies(as_dict=True)
                if cookies:
                    if not any(k in cookies for k in ["__zp_stoken__", "bst", "wt2"]):
                        return False
            except Exception:
                pass

            # DOM 检测：未登录元素
            for sel in [".btn-login", ".sign-btn", "[ka='header-login']"]:
                try:
                    if self.page.ele(f"css:{sel}", timeout=1):
                        return False
                except Exception:
                    pass

            # DOM 检测：已登录元素
            for sel in [".nav-figure", ".user-nav", ".header-username", ".nav-user-enter"]:
                try:
                    if self.page.ele(f"css:{sel}", timeout=1):
                        return True
                except Exception:
                    pass

            return True  # 有 token 但无明确 DOM 信号，保守认为已登录

        except Exception as e:
            self.logger.warning(f"登录状态检测异常: {e}")
            return True

    def _block_images(self):
        """登录后动态屏蔽图片请求，提升抓取速度。"""
        if not self.page:
            return
        try:
            self.page.set.blocked_urls([
                "*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp",
                "*.svg", "*.ico", "*.bmp", "*.avif",
            ])
            self.logger.info("已启用图片屏蔽")
        except Exception as e:
            self.logger.warning(f"图片屏蔽设置失败（可忽略）: {e}")

    # ------------------------------------------------------------------ #
    #  Cookie 持久化
    # ------------------------------------------------------------------ #

    async def _save_cookies_to_disk(self):
        """将当前浏览器 Cookie 保存到磁盘。"""
        if not self.page:
            return
        try:
            cookies = self.page.cookies()
            if not cookies:
                return
            path = self._cookie_file_path(self.account_index)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            account_name = self.accounts[self.account_index].get("name", f"account-{self.account_index + 1}")
            self.logger.info(f"Cookie 已保存 [{account_name}]（{len(cookies)} 条）→ {path}")
        except Exception as e:
            self.logger.warning(f"保存 Cookie 失败: {e}")

    def _cookie_file_path(self, index: int) -> str:
        return os.path.join(simple_script_dir, f"cookies_account_{index + 1}.json")

    def _load_cookies_from_disk(self, index: int) -> Optional[List[Dict[str, Any]]]:
        path = self._cookie_file_path(index)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) and data else None
        except Exception as e:
            self.logger.warning(f"从磁盘加载 Cookie 失败: {e}")
            return None

    def _parse_cookies(self, cookies: Any) -> List[Dict[str, Any]]:
        if isinstance(cookies, list):
            return cookies
        result: List[Dict[str, Any]] = []
        if isinstance(cookies, str):
            simple = SimpleCookie()
            simple.load(cookies)
            for key, morsel in simple.items():
                result.append({"name": key, "value": morsel.value, "domain": ".zhipin.com", "path": "/"})
        return result

    # ------------------------------------------------------------------ #
    #  代理轮换
    # ------------------------------------------------------------------ #

    async def _check_proxy_rotation(self):
        if self.proxy_rotate_seconds <= 0 or self.proxy_started_at <= 0:
            return
        if time.time() - self.proxy_started_at < self.proxy_rotate_seconds:
            return
        self.logger.info("触发定时代理轮换")
        await self._rotate_proxy_and_browser()

    async def _rotate_proxy_and_browser(self):
        if self.current_proxy:
            try:
                proxy_manager.remove_proxy(self.current_proxy)
            except Exception:
                pass
        await self._rebuild_browser()

    # ------------------------------------------------------------------ #
    #  账户管理
    # ------------------------------------------------------------------ #

    def _load_accounts(self) -> List[Dict[str, Any]]:
        raw = self.accounts_json or os.getenv("BOSS_LIST_ACCOUNTS", "").strip()
        if not raw:
            return [{"name": "default", "cookies": None, "user_data_dir": None}]
        try:
            data = json.loads(raw)
        except Exception:
            self.logger.warning("账户配置 JSON 解析失败，回退单账户模式")
            return [{"name": "default", "cookies": None, "user_data_dir": None}]
        if not isinstance(data, list) or not data:
            return [{"name": "default", "cookies": None, "user_data_dir": None}]
        normalized = [
            {
                "name": acc.get("name") or f"account-{i + 1}",
                "cookies": acc.get("cookies") or acc.get("cookie"),
                "user_data_dir": acc.get("user_data_dir"),
            }
            for i, acc in enumerate(data)
            if isinstance(acc, dict)
        ]
        return normalized or [{"name": "default", "cookies": None, "user_data_dir": None}]

    # ------------------------------------------------------------------ #
    #  数据库操作
    # ------------------------------------------------------------------ #

    async def _sync_db_status(self) -> bool:
        if not self.current_task_id:
            return False
        async with (await db_manager.get_session()) as session:
            task = await session.get(BossStuCrawlUrl, self.current_task_id)
            if not task:
                self.current_task_id = None
                return False
            if task.status == "paused":
                self.logger.info(f"任务 {self.current_task_id} 已暂停")
                return False
            if task.status == "stopped":
                self.logger.info(f"任务 {self.current_task_id} 已停止")
                await self._update_db_status(self.current_task_id, "stopped")
                self.current_task_id = None
                if self.target_task_id:
                    raise CloseSpider(reason="任务被停止")
                return False
            if task.status == "pending":
                task.status = "processing"
                await session.commit()
        return True

    async def _fetch_and_assign_new_task(self):
        async with (await db_manager.get_session()) as session:
            stmt = select(BossStuCrawlUrl).where(BossStuCrawlUrl.status == "pending")
            if self.target_task_id:
                stmt = stmt.where(BossStuCrawlUrl.id == self.target_task_id)
            stmt = stmt.order_by(BossStuCrawlUrl.id.asc()).limit(1)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()
            if not task:
                return
            task.status = "processing"
            await session.commit()
            self.current_task_id = task.id
            self.current_task_url = task.url
            self.current_task_major_name = task.major_name or ""
            self.current_page = 1  # BossStuCrawlUrl 无 page 字段，页码仅内存追踪
            self.current_task_retry = 0
            self.logger.info(f"领取任务 {task.id} [{task.major_name}]: {task.url}")

    async def _update_task_page(self, task_id: int, page: int):
        # BossStuCrawlUrl 无 page 字段，页码状态仅内存追踪，无需写入 DB
        pass

    async def _update_db_status(self, task_id: int, status: str, error_msg: Optional[str] = None):
        async with (await db_manager.get_session()) as session:
            stmt = (
                update(BossStuCrawlUrl)
                .where(BossStuCrawlUrl.id == task_id)
                .values(status=status, last_crawl_time=datetime.now(), error_msg=error_msg)
            )
            await session.execute(stmt)
            await session.commit()

    # ------------------------------------------------------------------ #
    #  工具方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def _replace_query_page(url: str, page: int) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        query["page"] = [str(page)]
        query_str = urlencode({k: v[0] for k, v in query.items()}, doseq=False)
        return urlunparse(parsed._replace(query=query_str))

    def _create_proxy_extension(self, proxy_url: str) -> str:
        """为带认证的代理创建 Chrome 扩展插件。"""
        proxy_url = proxy_url.replace("http://", "").replace("https://", "")
        auth, ip_port = proxy_url.split("@")
        username, password = auth.split(":")
        ip, port = ip_port.split(":")

        plugin_path = os.path.join(simple_script_dir, "proxy_auth_plugin")
        os.makedirs(plugin_path, exist_ok=True)

        manifest_json = """{
    "version": "1.0.0",
    "manifest_version": 2,
    "name": "Chrome Proxy",
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
