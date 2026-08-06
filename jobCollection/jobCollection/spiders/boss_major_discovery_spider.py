"""Discover BOSS school-major URLs without crawling job data."""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import scrapy
from DrissionPage import ChromiumOptions, ChromiumPage
from scrapy.exceptions import CloseSpider

from ..boss.tasks import (
    MajorUrlCandidate,
    SqlAlchemyTaskRepository,
    extract_major_candidates,
    generate_major_tasks,
    persist_major_catalog,
)


AUTH_COOKIE_NAMES = {"__zp_stoken__", "bst", "wt2"}
MAJOR_LINK_LOCATOR = "css:a[href*='/web/geek/jobs'][href*='position=']"


class BossMajorDiscoverySpider(scrapy.Spider):
    """Refresh the major URL catalog and generate stable major tasks."""

    name = "boss_major_discovery"
    allowed_domains = ["zhipin.com"]
    school_url = "https://www.zhipin.com/school/?ka=tab_school_recruit_click"
    custom_settings = {
        "CONCURRENT_REQUESTS": 1,
        "ITEM_PIPELINES": {},
    }

    def __init__(
        self,
        accounts_json: Optional[str] = None,
        accounts_file: Optional[str] = None,
        school_url: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.accounts_json = accounts_json or os.getenv("BOSS_LIST_ACCOUNTS", "")
        self.accounts_file = accounts_file or os.getenv("BOSS_LIST_ACCOUNTS_FILE", "")
        if school_url:
            self.school_url = school_url
        self.cookies = self._load_authenticated_cookies()
        self.page: Optional[ChromiumPage] = None

    def _read_accounts_json(self) -> str:
        if self.accounts_json.strip():
            return self.accounts_json.strip()
        if not self.accounts_file:
            return ""
        path = Path(self.accounts_file)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / "simple_script" / path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _load_authenticated_cookies(self) -> List[Dict[str, Any]]:
        raw = self._read_accounts_json()
        if not raw:
            return []
        try:
            accounts = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(accounts, list):
            return []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            cookies = account.get("cookies") or account.get("cookie") or []
            if not isinstance(cookies, list):
                continue
            names = {
                str(cookie.get("name"))
                for cookie in cookies
                if isinstance(cookie, dict) and cookie.get("name")
            }
            if names.intersection(AUTH_COOKIE_NAMES):
                return [cookie for cookie in cookies if isinstance(cookie, dict)]
        return []

    def _bootstrap_request(self) -> scrapy.Request:
        return scrapy.Request("data:,bootstrap", callback=self._bootstrap, dont_filter=True)

    def start_requests(self) -> Iterable[scrapy.Request]:
        if not self.cookies:
            self.logger.warning("No authenticated BOSS cookie; major discovery stays offline")
            return
        yield self._bootstrap_request()

    async def start(self):
        if not self.cookies:
            self.logger.warning("No authenticated BOSS cookie; major discovery stays offline")
            return
        yield self._bootstrap_request()

    @staticmethod
    def extract_candidates_from_page(page: Any) -> List[MajorUrlCandidate]:
        nodes = []
        for element in page.eles(MAJOR_LINK_LOCATOR, timeout=10):
            nodes.append(
                {
                    "href": element.attr("href") or "",
                    "text": getattr(element, "text", "") or "",
                    "data-major-code": element.attr("data-major-code") or "",
                }
            )
        return extract_major_candidates(nodes)

    @classmethod
    def collect_candidates_until_stable(
        cls,
        page: Any,
        *,
        stable_rounds: int = 3,
        max_rounds: int = 50,
        scroll_pixel: int = 800,
        settle_wait: Optional[Callable[[float], None]] = None,
        settle_seconds: float = 0.5,
    ) -> List[MajorUrlCandidate]:
        """Scroll until the number of valid major links stops growing."""
        if settle_seconds < 0 or settle_seconds > 5:
            raise ValueError("settle_seconds must be between 0 and 5")
        wait_after_scroll = settle_wait or time.sleep
        page.wait.eles_loaded(
            MAJOR_LINK_LOCATOR,
            timeout=30,
            any_one=True,
        )
        by_hash: Dict[str, MajorUrlCandidate] = {}
        stable_count = 0
        for round_index in range(max_rounds + 1):
            before = len(by_hash)
            for candidate in cls.extract_candidates_from_page(page):
                by_hash[candidate.url_hash] = candidate
            stable_count = stable_count + 1 if len(by_hash) == before else 0
            if stable_count >= stable_rounds:
                break
            if round_index >= max_rounds:
                break
            page.scroll.down(scroll_pixel)
            wait_after_scroll(settle_seconds)
        return list(by_hash.values())

    def _build_page(self) -> ChromiumPage:
        options = ChromiumOptions()
        user_data_path = os.getenv("BOSS_MAJOR_USER_DATA_DIR", "").strip()
        if user_data_path:
            options.set_user_data_path(user_data_path)
        page = ChromiumPage(options)
        page.set.cookies(self.cookies)
        return page

    def _collect_candidates_in_browser(self) -> List[MajorUrlCandidate]:
        """Own the complete synchronous browser lifecycle on one worker thread."""
        self.page = self._build_page()
        try:
            # DrissionPage clears captured packets on listen.start(), so this is
            # deliberately called once, before navigating to the school page.
            self.page.listen.start()
            self.page.get(
                self.school_url,
                show_errmsg=True,
                retry=1,
                interval=2,
                timeout=60,
            )
            return self.collect_candidates_until_stable(self.page)
        finally:
            self.page.quit()
            self.page = None

    async def _bootstrap(self, response: scrapy.http.Response) -> None:
        if not self.cookies:
            raise CloseSpider(reason="authenticated BOSS cookie required")

        # Import lazily so Scrapy discovery and offline fixture tests do not
        # create an asyncio-bound database manager at module import time.
        from common.databases.PostgresManager import db_manager

        await db_manager.initialize()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="boss-major")
        try:
            candidates = await asyncio.get_running_loop().run_in_executor(
                executor,
                self._collect_candidates_in_browser,
            )
            if not candidates:
                raise CloseSpider(reason="no valid BOSS major URLs discovered")

            source_version = datetime.now(timezone.utc).strftime("school-dom-%Y%m%d")
            async with (await db_manager.get_session()) as session:
                async with session.begin():
                    repository = SqlAlchemyTaskRepository(session)
                    catalog_stats = await persist_major_catalog(
                        repository,
                        candidates,
                        source_version,
                    )
                    task_stats = await generate_major_tasks(repository)
            self.logger.info(
                "major discovery completed: catalog=%s tasks=%s",
                catalog_stats,
                task_stats,
            )
        finally:
            executor.shutdown(wait=True)
