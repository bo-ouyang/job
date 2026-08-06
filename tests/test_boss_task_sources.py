import asyncio
from pathlib import Path
from types import SimpleNamespace


FIXTURE = Path(__file__).parent / "fixtures" / "boss_major_school.html"


class MemoryTaskRepository:
    def __init__(self, *, major_urls=(), cities=(), industries=()):
        self.major_urls = list(major_urls)
        self.cities = list(cities)
        self.industries = list(industries)
        self.tasks = {}

    async def list_major_urls(self):
        return self.major_urls

    async def list_city_level_codes(self):
        return [str(city.code) for city in self.cities if city.level == 1]

    async def list_boss_industry_leaf_codes(self):
        parent_codes = {str(industry.parent_id) for industry in self.industries if industry.parent_id is not None}
        return [
            str(industry.code)
            for industry in self.industries
            if industry.level == 1 and str(industry.code) not in parent_codes
        ]

    async def upsert_task_drafts(self, drafts):
        created = 0
        for draft in drafts:
            if draft.source_key not in self.tasks:
                self.tasks[draft.source_key] = draft
                created += 1
        return created


class MemoryMajorCatalogRepository:
    def __init__(self, *, majors=(), position_types=()):
        self.majors = list(majors)
        self.position_types = list(position_types)
        self.rows = {}

    async def list_majors(self):
        return self.majors

    async def list_position_types(self, codes):
        wanted = {str(code) for code in codes}
        return [item for item in self.position_types if str(item.code) in wanted]

    async def upsert_major_catalog(self, drafts, source_version):
        created = 0
        for draft in drafts:
            if draft.candidate.url_hash not in self.rows:
                created += 1
            self.rows[draft.candidate.url_hash] = (draft, source_version)
        return created


def test_school_fixture_extracts_only_major_job_links():
    from jobCollection.jobCollection.boss.tasks import extract_major_candidates_from_html

    candidates = extract_major_candidates_from_html(FIXTURE.read_text(encoding="utf-8"))

    assert [(item.major_name, item.major_code) for item in candidates] == [
        ("兽医学", "090401"),
        ("软件工程", None),
    ]
    assert candidates[0].position_codes == ("300401", "300403")
    assert candidates[0].experience_code == "108"
    assert "ka=" not in candidates[0].canonical_url


def test_major_candidate_preserves_source_experience_and_tracking_does_not_change_identity():
    from jobCollection.jobCollection.boss.tasks import parse_major_candidate

    first = parse_major_candidate(
        "/web/geek/jobs?position=2,1&experience=105&ka=first",
        "  兽医学  ",
    )
    second = parse_major_candidate(
        "/web/geek/jobs?ka=second&experience=105&position=1,2",
        "兽医学",
    )

    assert first.canonical_url == second.canonical_url
    assert first.url_hash == second.url_hash
    assert first.experience_code == "105"


def test_major_candidate_can_recover_name_from_ka_but_rejects_non_major_links():
    import pytest

    from jobCollection.jobCollection.boss.tasks import parse_major_candidate

    candidate = parse_major_candidate(
        "/web/geek/jobs?position=1&ka=major_filter_%E5%85%BD%E5%8C%BB%E5%AD%A6_click",
        "",
    )
    assert candidate.major_name == "兽医学"

    with pytest.raises(ValueError, match="position"):
        parse_major_candidate("/web/geek/jobs?city=101010100", "北京")

    with pytest.raises(ValueError, match="BOSS jobs URL"):
        parse_major_candidate("https://example.com/web/geek/jobs?position=1", "伪造专业")

    with pytest.raises(ValueError, match="BOSS jobs URL"):
        parse_major_candidate("https://www.zhipin.com/about?position=1", "伪造专业")


def test_major_task_draft_uses_catalog_id_and_high_priority():
    from jobCollection.jobCollection.boss.tasks import build_major_task_draft

    major_url = SimpleNamespace(
        id=42,
        major_id=7,
        canonical_url="https://www.zhipin.com/web/geek/jobs?experience=108&position=1,2",
        is_active=True,
    )
    draft = build_major_task_draft(major_url)

    assert draft.source_key == "major:42"
    assert draft.priority == 100
    assert draft.spider_name == "boss_task_drission"
    assert draft.spider_args == {
        "task_type": "major",
        "major_url_id": 42,
        "major_id": 7,
        "task_url": major_url.canonical_url,
    }


def test_city_industry_draft_has_canonical_url_low_priority_and_typed_args():
    from jobCollection.jobCollection.boss.tasks import build_city_industry_task_draft

    draft = build_city_industry_task_draft("101010100", "100020")

    assert draft.source_key == "city_industry:101010100:100020"
    assert draft.url == "https://www.zhipin.com/web/geek/jobs?city=101010100&industry=100020"
    assert draft.priority == 10
    assert draft.spider_name == "boss_task_drission"
    assert draft.spider_args == {
        "task_type": "city_industry",
        "city_code": "101010100",
        "industry_code": "100020",
        "task_url": draft.url,
    }


def test_city_industry_generation_is_n_times_m_and_idempotent():
    from jobCollection.jobCollection.boss.tasks import generate_city_industry_tasks

    repository = MemoryTaskRepository(
        cities=[
            SimpleNamespace(code=101010100, level=1),
            SimpleNamespace(code=110000, level=0),
            SimpleNamespace(code=101010101, level=2),
            SimpleNamespace(code=101020100, level=1),
        ],
        industries=[
            SimpleNamespace(code=100000, level=0, parent_id=None),
            SimpleNamespace(code=100010, level=1, parent_id=100000),
            SimpleNamespace(code=100020, level=1, parent_id=100000),
        ],
    )

    first = asyncio.run(generate_city_industry_tasks(repository))
    second = asyncio.run(generate_city_industry_tasks(repository))

    assert first.expected == 4
    assert (first.created, first.existing, first.disabled) == (4, 0, 0)
    assert (second.created, second.existing, second.disabled) == (0, 4, 0)
    assert set(repository.tasks) == {
        "city_industry:101010100:100010",
        "city_industry:101010100:100020",
        "city_industry:101020100:100010",
        "city_industry:101020100:100020",
    }


def test_major_generation_skips_disabled_catalog_rows_and_is_idempotent():
    from jobCollection.jobCollection.boss.tasks import generate_major_tasks

    repository = MemoryTaskRepository(
        major_urls=[
            SimpleNamespace(
                id=1,
                major_id=10,
                canonical_url="https://www.zhipin.com/web/geek/jobs?position=1",
                is_active=True,
            ),
            SimpleNamespace(
                id=2,
                major_id=None,
                canonical_url="https://www.zhipin.com/web/geek/jobs?position=2",
                is_active=False,
            ),
        ]
    )

    first = asyncio.run(generate_major_tasks(repository))
    second = asyncio.run(generate_major_tasks(repository))

    assert (first.expected, first.created, first.existing, first.disabled) == (1, 1, 0, 1)
    assert (second.expected, second.created, second.existing, second.disabled) == (1, 0, 1, 1)


def test_industry_leaf_predicate_requires_level_one_and_no_child():
    from jobCollection.jobCollection.boss.tasks import is_boss_industry_leaf

    child_parent_codes = {100000, 100020}
    assert not is_boss_industry_leaf(SimpleNamespace(code=100000, level=0), child_parent_codes)
    assert not is_boss_industry_leaf(SimpleNamespace(code=100020, level=1), child_parent_codes)
    assert is_boss_industry_leaf(SimpleNamespace(code=100021, level=1), child_parent_codes)


def test_catalog_resolution_matches_major_and_leaf_positions_and_records_missing_codes():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        resolve_major_catalog_candidate,
    )

    candidate = parse_major_candidate(
        "/web/geek/jobs?position=1,2&experience=108",
        "兽医学",
        "090401",
    )
    draft = resolve_major_catalog_candidate(
        candidate,
        majors=[SimpleNamespace(id=7, code="090401", name="兽医学")],
        position_types=[SimpleNamespace(id=11, code=1, is_leaf=True)],
    )

    assert draft.major_id == 7
    assert draft.position_type_ids == (11,)
    assert draft.parse_error == "unmatched position_type codes: 2"


def test_catalog_resolution_falls_back_to_major_name_and_rejects_non_leaf_position_match():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        resolve_major_catalog_candidate,
    )

    candidate = parse_major_candidate("/web/geek/jobs?position=1", "软件工程")
    draft = resolve_major_catalog_candidate(
        candidate,
        majors=[SimpleNamespace(id=8, code="080902", name="软件工程")],
        position_types=[SimpleNamespace(id=12, code=1, is_leaf=False)],
    )

    assert draft.major_id == 8
    assert draft.position_type_ids == ()
    assert draft.parse_error == "unmatched position_type codes: 1"


def test_catalog_resolution_records_unmatched_major_name():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        resolve_major_catalog_candidate,
    )

    candidate = parse_major_candidate("/web/geek/jobs?position=1", "未知专业")
    draft = resolve_major_catalog_candidate(candidate, majors=[], position_types=[])

    assert draft.major_id is None
    assert draft.parse_error == (
        "unmatched major name: 未知专业; unmatched position_type codes: 1"
    )


def test_major_catalog_persistence_is_idempotent_and_reports_parse_errors():
    from jobCollection.jobCollection.boss.tasks import (
        parse_major_candidate,
        persist_major_catalog,
    )

    repository = MemoryMajorCatalogRepository(
        majors=[SimpleNamespace(id=7, code="090401", name="兽医学")],
        position_types=[SimpleNamespace(id=11, code=1, is_leaf=True)],
    )
    candidates = [
        parse_major_candidate("/web/geek/jobs?position=1", "兽医学", "090401"),
        parse_major_candidate("/web/geek/jobs?position=2", "未知专业"),
    ]

    first = asyncio.run(persist_major_catalog(repository, candidates, "fixture-v1"))
    second = asyncio.run(persist_major_catalog(repository, candidates, "fixture-v2"))

    assert (first.created, first.existing, first.parse_errors) == (2, 0, 1)
    assert (second.created, second.existing, second.parse_errors) == (0, 2, 1)
    assert {version for _, version in repository.rows.values()} == {"fixture-v2"}


def test_major_discovery_without_authenticated_cookie_schedules_no_navigation():
    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    spider = BossMajorDiscoverySpider(accounts_json='[{"cookies": []}]')

    assert list(spider.start_requests()) == []


def test_major_discovery_with_authenticated_cookie_only_schedules_local_bootstrap():
    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    spider = BossMajorDiscoverySpider(
        accounts_json='[{"cookies": [{"name": "__zp_stoken__", "value": "test"}]}]'
    )
    requests = list(spider.start_requests())

    assert len(requests) == 1
    assert requests[0].url.startswith("data:")
    assert "zhipin.com" not in requests[0].url


def test_major_discovery_dom_adapter_uses_drissionpage_element_contract():
    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    class Element:
        text = "兽医学"

        def attr(self, name):
            return {
                "href": "/web/geek/jobs?position=2,1&experience=108",
                "data-major-code": "090401",
            }.get(name)

    class Page:
        def __init__(self):
            self.locator = None

        def eles(self, locator, timeout=None):
            self.locator = (locator, timeout)
            return [Element()]

    page = Page()
    candidates = BossMajorDiscoverySpider.extract_candidates_from_page(page)

    assert page.locator == (
        "css:a[href*='/web/geek/jobs'][href*='position=']",
        10,
    )
    assert len(candidates) == 1
    assert candidates[0].major_code == "090401"
    assert candidates[0].experience_code == "108"


def test_major_discovery_scrolls_until_matching_links_are_stable():
    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    class Element:
        def __init__(self, href, text):
            self._href = href
            self.text = text

        def attr(self, name):
            return self._href if name == "href" else ""

    class Page:
        def __init__(self):
            self.round = 0
            self.scroll = SimpleNamespace(down=self._scroll)
            self.wait = SimpleNamespace(eles_loaded=self._wait_loaded)

        def _wait_loaded(self, locator, timeout=None, any_one=False):
            self.wait_call = (locator, timeout, any_one)

        def _scroll(self, pixel):
            self.round += 1

        def eles(self, locator, timeout=None):
            self.locator = (locator, timeout)
            valid = [Element("/web/geek/jobs?position=1", "兽医学")]
            if self.round >= 1:
                valid.append(Element("/web/geek/jobs?position=2", "软件工程"))
            return valid + [Element("/about", "关于")]

    page = Page()
    candidates = BossMajorDiscoverySpider.collect_candidates_until_stable(
        page,
        stable_rounds=2,
        max_rounds=8,
        settle_wait=lambda _seconds: None,
    )

    assert page.wait_call[0] == "css:a[href*='/web/geek/jobs'][href*='position=']"
    assert page.locator[0] == "css:a[href*='/web/geek/jobs'][href*='position=']"
    assert [candidate.major_name for candidate in candidates] == ["兽医学", "软件工程"]
    assert page.round == 3


def test_major_discovery_waits_for_lazy_dom_after_each_scroll():
    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    class Element:
        def __init__(self, href, text):
            self._href = href
            self.text = text

        def attr(self, name):
            return self._href if name == "href" else ""

    class Page:
        def __init__(self):
            self.loaded = False
            self.pending = False
            self.scroll = SimpleNamespace(down=self._scroll)
            self.wait = SimpleNamespace(eles_loaded=lambda *args, **kwargs: None)

        def _scroll(self, _pixel):
            self.pending = True

        def settle(self, _seconds):
            if self.pending:
                self.loaded = True
                self.pending = False

        def eles(self, _locator, timeout=None):
            result = [Element("/web/geek/jobs?position=1", "兽医学")]
            if self.loaded:
                result.append(Element("/web/geek/jobs?position=2", "软件工程"))
            return result

    page = Page()
    candidates = BossMajorDiscoverySpider.collect_candidates_until_stable(
        page,
        stable_rounds=1,
        max_rounds=2,
        settle_wait=page.settle,
        settle_seconds=0.1,
    )

    assert [candidate.major_name for candidate in candidates] == ["兽医学", "软件工程"]


def test_major_discovery_async_callback_offloads_browser_lifecycle():
    import inspect

    from jobCollection.jobCollection.spiders.boss_major_discovery_spider import (
        BossMajorDiscoverySpider,
    )

    source = inspect.getsource(BossMajorDiscoverySpider._bootstrap)

    assert "run_in_executor" in source
    assert "_collect_candidates_in_browser" in source
