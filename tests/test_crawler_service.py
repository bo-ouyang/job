import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "jobCollectionWebApi"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from services.crawler_service import CrawlerService  # noqa: E402


def test_legacy_filter_task_has_stable_canonical_identity():
    filters_a = [
        SimpleNamespace(filter_name="industry", filter_value="100020"),
        SimpleNamespace(filter_name="city", filter_value="101010100"),
    ]
    filters_b = list(reversed(filters_a))

    first = CrawlerService.build_filter_task_draft(filters_a, "ka=tracking")
    second = CrawlerService.build_filter_task_draft(filters_b, "ka=other")

    assert first.url == (
        "https://www.zhipin.com/web/geek/jobs?city=101010100&industry=100020"
    )
    assert second.url == first.url
    assert first.url_hash == second.url_hash
    assert first.source_key == second.source_key
    assert first.spider_name == "boss_task_drission"


def test_crawler_service_has_no_process_or_status_control_plane():
    assert not hasattr(CrawlerService, "run_crawler_task")
    assert not hasattr(CrawlerService, "update_task_status")
    assert not hasattr(CrawlerService, "reset_tasks")


def test_filter_generation_uses_shared_task_repository(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(
                    all=lambda: [
                        SimpleNamespace(filter_name="city", filter_value="101010100"),
                        SimpleNamespace(filter_name="industry", filter_value="100020"),
                    ]
                )
            )

        async def commit(self):
            pass

    class Repository:
        received = []

        def __init__(self, session):
            self.session = session

        async def upsert_task_drafts(self, drafts):
            self.__class__.received = list(drafts)
            return 1

    monkeypatch.setattr(
        "services.crawler_service.db_manager.async_session", lambda: Session()
    )
    monkeypatch.setattr("services.crawler_service.SqlAlchemyTaskRepository", Repository)

    created = asyncio.run(CrawlerService.generate_tasks_from_filters())

    assert created == 1
    assert len(Repository.received) == 1
    assert Repository.received[0].source_key.startswith("manual:")
