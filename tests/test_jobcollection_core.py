import importlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRAPY_ROOT = ROOT / "jobCollection"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRAPY_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRAPY_ROOT))


from jobCollection.boss.parsers import (  # noqa: E402
    build_boss_job_item,
    extract_jobs_and_has_more,
    parse_job_description,
)
from jobCollection.boss import proxy as proxy_module  # noqa: E402
from jobCollection.boss.proxy import (  # noqa: E402
    ProxyPoolManager,
    create_proxy_auth_extension,
    load_proxy_pool_config,
    parse_authenticated_proxy_url,
)
from jobCollection.items.boss_job_item import BossJobItem  # noqa: E402


@pytest.mark.parametrize(
    ("payload", "expected_jobs", "expected_has_more"),
    [
        ({"zpData": {"jobList": [{"encryptJobId": "zp"}], "hasMore": True}}, ["zp"], True),
        ({"data": {"jobList": [{"encryptJobId": "data"}], "hasMore": False}}, ["data"], False),
        ({"list": [{"encryptJobId": "flat"}], "hasMore": 1}, ["flat"], True),
        (None, [], None),
    ],
)
def test_extract_jobs_and_has_more_normalizes_payload_shapes(
    payload, expected_jobs, expected_has_more
):
    jobs, has_more = extract_jobs_and_has_more(payload)

    assert [job["encryptJobId"] for job in jobs] == expected_jobs
    assert has_more is expected_has_more


def test_build_boss_job_item_combines_url_context_and_payload_fields():
    item = build_boss_job_item(
        {
            "jobName": "Python Developer",
            "salaryDesc": "20-30K",
            "jobExperience": "3-5年",
            "jobDegree": "本科",
            "cityName": "深圳",
            "areaDistrict": "南山",
            "businessDistrict": "科技园",
            "jobLabels": ["双休"],
            "skills": ["Python"],
            "welfareList": ["五险一金"],
            "encryptJobId": "job-1",
            "encryptBrandId": "brand-1",
            "brandName": "Example",
            "brandLogo": "logo.png",
            "brandStageName": "已上市",
            "brandIndustry": "互联网",
            "brandScaleName": "100-499人",
            "gps": {"longitude": 113.9, "latitude": 22.5},
            "bossName": "王女士",
            "bossTitle": "HR",
            "bossAvatar": "avatar.png",
        },
        "https://www.zhipin.com/web/geek/jobs?industry=100020&city=101280600",
        major_name="软件工程",
    )

    assert isinstance(item, BossJobItem)
    assert item["job_name"] == "Python Developer"
    assert item["encrypt_job_id"] == "job-1"
    assert item["industry_code"] == 100020
    assert item["city_code"] == 101280600
    assert item["longitude"] == 113.9
    assert item["latitude"] == 22.5
    assert item["boss_name"] == "王女士"
    assert item["major_name"] == "软件工程"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (
            '<section class="job-detail-section"><div class="job-sec-text">'
            "负责 API 开发 <span>维护服务</span></div></section>",
            "负责 API 开发\n维护服务",
        ),
        (
            '<div class="job-detail-body"><div class="desc">'
            "设计系统 <p>编写测试</p></div></div>",
            "设计系统\n编写测试",
        ),
    ],
)
def test_parse_job_description_supports_both_retained_dom_shapes(html, expected):
    assert parse_job_description(html) == expected


def test_parse_authenticated_proxy_url_decodes_credentials():
    parsed = parse_authenticated_proxy_url(
        "http://crawler:p%40ss@127.0.0.1:8080"
    )

    assert parsed == {
        "scheme": "http",
        "host": "127.0.0.1",
        "port": 8080,
        "username": "crawler",
        "password": "p@ss",
    }


def test_proxy_pool_config_comes_only_from_environment():
    assert load_proxy_pool_config({}) == {
        "api_url": "",
        "username": "",
        "password": "",
        "min_pool_size": 1,
    }
    assert load_proxy_pool_config(
        {
            "BOSS_PROXY_API_URL": "https://proxy.example.test/pool",
            "BOSS_PROXY_USERNAME": "env-user",
            "BOSS_PROXY_PASSWORD": "env-pass",
            "BOSS_PROXY_MIN_POOL_SIZE": "2",
        }
    )["password"] == "env-pass"


class _ProxyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.mark.parametrize("payload", [None, [], {"data": None}])
def test_proxy_pool_rejects_malformed_success_payloads(monkeypatch, payload):
    monkeypatch.setattr(
        "jobCollection.boss.proxy.httpx.get",
        lambda *args, **kwargs: _ProxyResponse(payload),
    )
    manager = ProxyPoolManager(
        {"api_url": "https://proxy.example.test", "min_pool_size": 1}
    )

    assert manager.fetch_proxies() is False
    assert manager.proxy_pool == []


def test_proxy_pool_percent_encodes_environment_credentials(monkeypatch):
    monkeypatch.setattr(
        "jobCollection.boss.proxy.httpx.get",
        lambda *args, **kwargs: _ProxyResponse(
            {"code": 0, "data": {"proxy_list": ["127.0.0.1:8080"]}}
        ),
    )
    manager = ProxyPoolManager(
        {
            "api_url": "https://proxy.example.test",
            "username": "crawler@tenant",
            "password": "p:a/ss",
            "min_pool_size": 1,
        }
    )

    assert manager.fetch_proxies() is True
    assert parse_authenticated_proxy_url(manager.get_proxy()) == {
        "scheme": "http",
        "host": "127.0.0.1",
        "port": 8080,
        "username": "crawler@tenant",
        "password": "p:a/ss",
    }


def test_create_proxy_auth_extension_uses_arguments_without_source_defaults(tmp_path):
    extension_path = Path(
        create_proxy_auth_extension(
            "http://runtime-user:runtime-pass@10.0.0.8:9000",
            tmp_path,
            "detail_1",
        )
    )

    manifest = json.loads((extension_path / "manifest.json").read_text(encoding="utf-8"))
    background = (extension_path / "background.js").read_text(encoding="utf-8")
    source = (SCRAPY_ROOT / "jobCollection" / "boss" / "proxy.py").read_text(encoding="utf-8")

    assert manifest["name"] == "BOSS Proxy detail_1"
    assert 'host: "10.0.0.8"' in background
    assert 'username: "runtime-user"' in background
    assert 'password: "runtime-pass"' in background
    assert "d2006816196" not in source
    assert "xc1zag9a" not in source
    assert "secret_id=" not in source


def test_proxy_auth_extensions_are_unique_and_cleanup_removes_credentials(tmp_path):
    first = Path(
        create_proxy_auth_extension(
            "http://user:secret@127.0.0.1:8080", tmp_path, "list_1"
        )
    )
    second = Path(
        create_proxy_auth_extension(
            "http://user:secret@127.0.0.1:8080", tmp_path, "list_1"
        )
    )

    assert first != second
    assert first.exists() and second.exists()

    proxy_module.cleanup_proxy_auth_extension(first)

    assert not first.exists()
    assert second.exists()


@pytest.mark.parametrize(
    "module_name",
    [
        "jobCollection.spiders.boss_list_drission_spider",
        "jobCollection.spiders.boss_detail_drission_spider",
    ],
)
def test_retained_spiders_import_on_python39(module_name):
    module = importlib.import_module(module_name)

    assert module is not None


def test_postgres_manager_can_be_constructed_after_asyncio_run_closes_default_loop():
    import asyncio

    asyncio.run(asyncio.sleep(0))

    from common.databases.PostgresManager import PostgresManager

    manager = PostgresManager()

    assert manager._init_lock is None


def test_postgres_manager_close_allows_reinitialization_on_a_new_event_loop():
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from common.databases.PostgresManager import PostgresManager

    class Connection:
        async def execute(self, _statement):
            return SimpleNamespace(scalar=lambda: None)

    class Engine:
        def __init__(self):
            self.dispose_count = 0

        @asynccontextmanager
        async def begin(self):
            yield Connection()

        async def dispose(self):
            self.dispose_count += 1

    manager = PostgresManager()
    engine = Engine()
    manager.engine = engine

    async def initialize_then_close():
        await manager.initialize()
        first_lock = manager._init_lock
        await manager.close()
        return first_lock

    first_lock = asyncio.run(initialize_then_close())
    second_lock = asyncio.run(initialize_then_close())

    assert first_lock is not second_lock
    assert manager._init_lock is None
    assert manager.async_session is None
    assert engine.dispose_count == 2
