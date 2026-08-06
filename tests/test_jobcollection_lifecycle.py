import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import scrapy
from scrapy.exceptions import CloseSpider, DontCloseSpider, DropItem


ROOT = Path(__file__).resolve().parents[1]
SCRAPY_ROOT = ROOT / "jobCollection"
for path in (ROOT, SCRAPY_ROOT, ROOT / "jobCollectionWebApi"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from jobCollection.items.boss_job_item import BossJobDetailItem, BossJobItem  # noqa: E402
from jobCollection.pipelines.boss_pipeline import BossJobPipeline  # noqa: E402
from jobCollection.pipelines.redis_dedup_pipeline import (  # noqa: E402
    RedisDeduplicationPipeline,
)
from jobCollection.spiders.boss_detail_drission_spider import (  # noqa: E402
    BossDetailDrissionSpider,
)
from jobCollection.spiders.boss_list_drission_spider import (  # noqa: E402
    BossListDrissionSpider,
)


async def _collect_async(iterable):
    return [value async for value in iterable]


def test_list_spider_init_does_not_require_an_event_loop():
    asyncio.run(asyncio.sleep(0))

    spider = BossListDrissionSpider()

    assert spider is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "spider_cls", [BossListDrissionSpider, BossDetailDrissionSpider]
)
async def test_scrapy_old_and_new_startup_share_one_bootstrap_request(spider_cls):
    spider = spider_cls()
    old_request = list(spider.start_requests())[0]
    new_request = (await _collect_async(spider.start()))[0]

    assert old_request.url == "data:,bootstrap"
    assert new_request.url == old_request.url
    assert old_request.callback.__func__ is spider._bootstrap.__func__
    assert new_request.callback.__func__ is spider._bootstrap.__func__


@pytest.mark.asyncio
async def test_list_target_task_closes_after_done_instead_of_becoming_processing():
    spider = BossListDrissionSpider(task_id="42", task_url="https://example.test/jobs")
    spider.current_task_id = 42
    spider.current_task_url = "https://example.test/jobs"
    spider._fetch_all_by_scroll = AsyncMock(return_value=(3, True))
    spider._update_db_status = AsyncMock()

    await spider._process_current_page()
    spider._update_db_status.assert_not_awaited()
    with pytest.raises(CloseSpider):
        await spider._finalize_pending_task()

    spider._update_db_status.assert_awaited_once_with(42, "done", pid=None)


@pytest.mark.asyncio
async def test_list_yields_items_before_marking_target_done_and_closing(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    spider = BossListDrissionSpider(task_id="42", task_url="https://example.test/jobs")
    spider.current_task_id = 42
    spider.current_task_url = "https://example.test/jobs"
    item = BossJobItem(encrypt_job_id="enc")

    async def fetch(_url):
        await spider.item_queue.put(item)
        return 1, True

    spider._fetch_all_by_scroll = fetch
    spider._sync_db_status = AsyncMock(return_value=True)
    spider._update_db_status = AsyncMock()
    generator = spider.parse_loop(None)

    assert await generator.__anext__() is item
    spider._update_db_status.assert_not_awaited()
    with pytest.raises(CloseSpider):
        await generator.__anext__()
    spider._update_db_status.assert_awaited_once_with(42, "done", pid=None)


@pytest.mark.asyncio
async def test_list_empty_payload_is_a_failed_fetch():
    spider = BossListDrissionSpider()
    spider.page = SimpleNamespace(
        get=MagicMock(),
        url="https://www.zhipin.com/web/geek/jobs",
    )
    spider._scroll_to_load = AsyncMock()
    spider._fetch_job_list_by_js = MagicMock(return_value=None)

    assert await spider._fetch_all_by_scroll("https://example.test/jobs") == (0, False)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"zpData": {}}])
async def test_list_empty_envelope_is_a_failed_fetch(payload):
    spider = BossListDrissionSpider()
    spider.page = SimpleNamespace(get=MagicMock(), url="https://www.zhipin.com/jobs")
    spider._scroll_to_load = AsyncMock()
    spider._fetch_job_list_by_js = MagicMock(return_value=payload)

    assert await spider._fetch_all_by_scroll("https://example.test/jobs") == (0, False)


@pytest.mark.asyncio
async def test_list_explicit_empty_job_list_is_a_successful_fetch():
    spider = BossListDrissionSpider()
    spider.page = SimpleNamespace(get=MagicMock(), url="https://www.zhipin.com/jobs")
    spider._scroll_to_load = AsyncMock()
    spider._fetch_job_list_by_js = MagicMock(
        return_value={"zpData": {"jobList": [], "hasMore": False}}
    )

    assert await spider._fetch_all_by_scroll("https://example.test/jobs") == (0, True)


@pytest.mark.asyncio
async def test_list_enforces_max_pages_and_advances_current_page(monkeypatch):
    monkeypatch.setenv("BOSS_MAX_PAGES_PER_TASK", "2")
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    spider = BossListDrissionSpider()
    spider.page = SimpleNamespace(
        get=MagicMock(),
        url="https://www.zhipin.com/web/geek/jobs",
    )
    spider.current_page = 1
    spider._scroll_to_load = AsyncMock()
    payload = {"zpData": {"jobList": [], "hasMore": True}}
    spider._fetch_job_list_by_js = MagicMock(
        side_effect=[payload, payload, RuntimeError("page limit not enforced")]
    )

    assert await spider._fetch_all_by_scroll("https://example.test/jobs") == (0, True)
    assert spider._fetch_job_list_by_js.call_count == 2
    assert spider.current_page == 3


class _Transaction:
    def __init__(self):
        self.active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.active = False


class _Session:
    def __init__(self, result=None):
        self.result = result
        self.statements = []
        self.transaction = _Transaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def begin(self):
        return self.transaction

    async def execute(self, statement):
        self.statements.append(statement)
        return self.result

    async def commit(self):
        return None


class _ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


@pytest.mark.asyncio
async def test_detail_claim_is_atomic_skip_locked_and_not_major_filtered(monkeypatch):
    job = SimpleNamespace(id=1, encrypt_job_id="enc", is_crawl=0, updated_at=None)
    session = _Session(_ScalarResult([job]))
    get_session = AsyncMock(return_value=session)
    monkeypatch.setattr(
        "jobCollection.spiders.boss_detail_drission_spider.db_manager.get_session",
        get_session,
    )
    spider = BossDetailDrissionSpider()

    assert await spider._fetch_tasks() == [job]
    statement = session.statements[0]
    assert statement._for_update_arg.skip_locked is True
    assert "major_name" not in str(statement.whereclause)
    assert job.is_crawl == 2


@pytest.mark.asyncio
async def test_list_claim_is_atomic_and_skip_locked(monkeypatch):
    task = SimpleNamespace(id=2, url="https://example.test/jobs", status="pending")
    session = _Session(SimpleNamespace(scalar_one_or_none=lambda: task))
    monkeypatch.setattr(
        "jobCollection.spiders.boss_list_drission_spider.db_manager.get_session",
        AsyncMock(return_value=session),
    )
    spider = BossListDrissionSpider()

    await spider._fetch_and_assign_new_task()

    statement = session.statements[0]
    assert statement._for_update_arg.skip_locked is True
    assert task.status == "processing"


@pytest.mark.asyncio
async def test_detail_parse_failure_reverts_job_to_pending(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    spider = BossDetailDrissionSpider()
    spider.page = SimpleNamespace(html="<html>no description</html>")
    spider._navigate = AsyncMock(return_value=True)
    spider._revert_task = AsyncMock()
    job = SimpleNamespace(encrypt_job_id="enc")

    assert await spider._process_job(job) is None
    spider._revert_task.assert_awaited_once_with("enc")


@pytest.mark.asyncio
async def test_detail_success_produces_pipeline_item_without_direct_db_write(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    spider = BossDetailDrissionSpider()
    spider.page = SimpleNamespace(
        html='<div class="job-detail-section"><div class="job-sec-text">Detail</div></div>'
    )
    spider._navigate = AsyncMock(return_value=True)
    spider._update_job = AsyncMock()
    item = await spider._process_job(SimpleNamespace(encrypt_job_id="enc"))

    assert isinstance(item, BossJobDetailItem)
    assert item["encrypt_job_id"] == "enc"
    assert item["job_desc"] == "Detail"
    spider._update_job.assert_not_awaited()
    assert "jobCollection.pipelines.boss_pipeline.BossJobPipeline" in spider.custom_settings["ITEM_PIPELINES"]


@pytest.mark.asyncio
async def test_detail_navigation_uses_drissionpage_eles_loaded():
    wait = SimpleNamespace(eles_loaded=MagicMock(return_value=True))
    spider = BossDetailDrissionSpider()
    spider.page = SimpleNamespace(get=MagicMock(), wait=wait, url="https://www.zhipin.com/job_detail/x.html")

    assert await spider._navigate("https://www.zhipin.com/job_detail/x.html") is True
    wait.eles_loaded.assert_called_once()


def test_redis_duplicate_raises_drop_item():
    pipeline = RedisDeduplicationPipeline("localhost", 6379, 0, None, 10, [1])
    pipeline.server = object()
    pipeline.bf = MagicMock()
    pipeline.bf.is_contains.return_value = True

    with pytest.raises(DropItem):
        pipeline.process_item(BossJobItem(encrypt_job_id="duplicate"), SimpleNamespace(logger=MagicMock()))


def test_redis_bloom_key_has_ttl(monkeypatch):
    server = MagicMock()
    server.ping.return_value = True
    monkeypatch.setenv("BOSS_BLOOM_TTL_SECONDS", "86400")
    monkeypatch.setattr("jobCollection.pipelines.redis_dedup_pipeline.redis.Redis", lambda **kwargs: server)
    pipeline = RedisDeduplicationPipeline("localhost", 6379, 0, None, 10, [1])

    pipeline.open_spider(SimpleNamespace(name="boss_list_drission"))
    pipeline.bf = MagicMock()
    pipeline.bf.is_contains.return_value = False
    server.expire.assert_not_called()
    pipeline.process_item(
        BossJobItem(encrypt_job_id="first"), SimpleNamespace(logger=MagicMock())
    )

    server.expire.assert_called_once_with(pipeline.bf_key, 86400)
    assert len(pipeline.bf_key.rsplit(":", 1)[-1]) == 8


@pytest.mark.asyncio
async def test_pipeline_final_detail_failure_reverts_to_pending(monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    pipeline = BossJobPipeline()
    pipeline._db_write = AsyncMock(side_effect=RuntimeError("db unavailable"))
    pipeline._revert_detail_items = AsyncMock()
    item = BossJobDetailItem(encrypt_job_id="enc", job_desc="detail")

    assert await pipeline._write_batch_with_retries([item]) is False
    pipeline._revert_detail_items.assert_awaited_once_with([item])


@pytest.mark.asyncio
async def test_pipeline_process_item_waits_for_database_write():
    pipeline = BossJobPipeline()
    write_started = asyncio.Event()
    allow_write = asyncio.Event()

    async def write(_batch):
        write_started.set()
        await allow_write.wait()
        return True

    pipeline._write_batch_with_retries = write
    item = BossJobItem(encrypt_job_id="enc")
    spider = SimpleNamespace(pipeline_failed=False)

    processing = asyncio.create_task(pipeline.process_item(item, spider))
    await asyncio.sleep(0)
    assert write_started.is_set() is True
    assert processing.done() is False

    allow_write.set()
    assert await processing is item


@pytest.mark.asyncio
async def test_pipeline_failure_marks_spider_and_revert_failure_is_contained(monkeypatch):
    from scrapy.exceptions import DropItem

    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    pipeline = BossJobPipeline()
    pipeline._db_write = AsyncMock(side_effect=RuntimeError("db unavailable"))
    pipeline._revert_detail_items = AsyncMock(
        side_effect=RuntimeError("rollback unavailable")
    )
    spider = SimpleNamespace(pipeline_failed=False)
    item = BossJobDetailItem(encrypt_job_id="enc", job_desc="detail")

    with pytest.raises(DropItem, match="PostgreSQL write failed"):
        await pipeline.process_item(item, spider)
    assert spider.pipeline_failed is True


def test_retained_spiders_serialize_item_pipeline_processing():
    assert BossListDrissionSpider.custom_settings["CONCURRENT_ITEMS"] == 1
    assert BossDetailDrissionSpider.custom_settings["CONCURRENT_ITEMS"] == 1


@pytest.mark.asyncio
async def test_list_pipeline_failure_marks_task_error_instead_of_done():
    spider = BossListDrissionSpider(task_id="42")
    spider.current_task_id = 42
    spider.pipeline_failed = True
    spider._pending_completion = (42, 3, True)
    spider._update_db_status = AsyncMock()

    with pytest.raises(CloseSpider):
        await spider._finalize_pending_task()

    args, kwargs = spider._update_db_status.await_args
    assert args[:2] == (42, "error")
    assert kwargs["pid"] is None


@pytest.mark.asyncio
async def test_list_pending_completion_survives_status_write_failure():
    spider = BossListDrissionSpider()
    pending = (42, 3, False)
    spider._pending_completion = pending
    spider._update_db_status = AsyncMock(side_effect=RuntimeError("db unavailable"))

    with pytest.raises(RuntimeError, match="db unavailable"):
        await spider._finalize_pending_task()

    assert spider._pending_completion == pending


@pytest.mark.asyncio
async def test_es_dispatch_happens_after_transaction_commit(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        "jobCollection.pipelines.boss_pipeline.db_manager.get_session",
        AsyncMock(return_value=session),
    )
    pipeline = BossJobPipeline()
    pipeline._write_jobs = AsyncMock(return_value=[7])
    dispatched = []

    def dispatch(job_id):
        assert session.transaction.active is False
        dispatched.append(job_id)

    pipeline._dispatch_es_sync = dispatch
    await pipeline._db_write([BossJobItem(encrypt_job_id="enc")])

    assert dispatched == [7]


@pytest.mark.asyncio
async def test_list_done_status_clears_pid(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        "jobCollection.spiders.boss_list_drission_spider.db_manager.get_session",
        AsyncMock(return_value=session),
    )
    spider = BossListDrissionSpider()

    await spider._update_db_status(42, "done", pid=None)

    assert session.statements[0].compile().params["pid"] is None


@pytest.mark.asyncio
async def test_list_login_failure_closes_before_loop(monkeypatch):
    monkeypatch.setattr(
        "jobCollection.spiders.boss_list_drission_spider.db_manager.initialize",
        AsyncMock(),
    )
    spider = BossListDrissionSpider()
    spider._rebuild_browser = AsyncMock(return_value=False)

    with pytest.raises(CloseSpider):
        await spider._bootstrap(None).__anext__()


def test_login_cookie_check_uses_supported_drissionpage_api():
    spider = BossListDrissionSpider()
    cookies = MagicMock(return_value=[{"name": "__zp_stoken__", "value": "token"}])
    spider.page = SimpleNamespace(
        url="https://www.zhipin.com/",
        cookies=cookies,
        ele=MagicMock(return_value=None),
    )

    assert spider._is_logged_in() is True
    cookies.assert_called_once_with()


@pytest.mark.parametrize(
    "cookies",
    [MagicMock(return_value=[]), MagicMock(side_effect=RuntimeError("browser gone"))],
)
def test_login_check_requires_an_explicit_authenticated_signal(cookies):
    spider = BossListDrissionSpider()
    spider.page = SimpleNamespace(
        url="https://www.zhipin.com/",
        cookies=cookies,
        ele=MagicMock(return_value=None),
    )

    assert spider._is_logged_in() is False


@pytest.mark.asyncio
async def test_list_close_best_effort_clears_target_pid():
    spider = BossListDrissionSpider(task_id="42")
    spider._clear_target_pid = AsyncMock(side_effect=RuntimeError("db unavailable"))

    await spider.spider_closed(spider)

    spider._clear_target_pid.assert_awaited_once_with()


@pytest.mark.parametrize("spider_cls", [BossListDrissionSpider, BossDetailDrissionSpider])
def test_idle_reschedules_with_current_engine_signature(spider_cls):
    spider = spider_cls()
    spider.crawler = SimpleNamespace(engine=SimpleNamespace(crawl=MagicMock()))
    handler = spider.spider_idle if isinstance(spider, BossListDrissionSpider) else spider._spider_idle

    with pytest.raises(DontCloseSpider):
        handler(spider)

    args, kwargs = spider.crawler.engine.crawl.call_args
    assert len(args) == 1
    assert isinstance(args[0], scrapy.Request)


def test_job_api_url_overrides_existing_page_parameter():
    spider = BossListDrissionSpider()
    spider.current_page = 3

    api_url = spider._build_job_api_url(
        "https://www.zhipin.com/web/geek/jobs?city=1&page=1"
    )

    assert "page=3" in api_url
    assert "page=1" not in api_url


def test_bloom_hash_has_no_hidden_optional_dependency():
    source = (
        SCRAPY_ROOT / "jobCollection" / "pipelines" / "redis_dedup_pipeline.py"
    ).read_text(encoding="utf-8")
    assert "import mmh3" not in source
