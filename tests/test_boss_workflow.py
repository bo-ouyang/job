from dataclasses import dataclass
from types import SimpleNamespace


LIST_URL = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?page=1"
DETAIL_URL = "https://www.zhipin.com/wapi/zpgeek/job/detail.json"
TASK_URL = "https://www.zhipin.com/web/geek/jobs?position=1"


@dataclass
class FakePacket:
    url: str
    body: object
    status: int = 200

    @property
    def response(self):
        return SimpleNamespace(body=self.body, status=self.status)


class FakeBrowser:
    def __init__(
        self,
        *,
        cards=(),
        navigate_packets=(),
        click_packets=None,
        scroll_cards=(),
        click_errors=None,
        drain_errors=None,
    ):
        self._cards = list(cards)
        self._navigate_packets = list(navigate_packets)
        self._click_packets = {
            job_id: [list(batch) for batch in batches]
            for job_id, batches in (click_packets or {}).items()
        }
        self._scroll_cards = [list(batch) for batch in scroll_cards]
        self._click_errors = {
            job_id: list(errors) for job_id, errors in (click_errors or {}).items()
        }
        self._drain_errors = list(drain_errors or ())
        self._queue = []
        self.current_url = TASK_URL
        self.calls = []
        self.click_counts = {}

    def start_listener(self, targets):
        self.calls.append(("listen", tuple(targets)))

    def navigate(self, url):
        self.calls.append(("navigate", url))
        if self.current_url == TASK_URL:
            self.current_url = url
        self._queue.extend(self._navigate_packets)

    def drain_packets(self, timeout):
        self.calls.append(("drain", timeout))
        if self._drain_errors:
            error = self._drain_errors.pop(0)
            if error is not None:
                raise error
        packets, self._queue = self._queue, []
        return packets

    def cards(self):
        return list(self._cards)

    def click(self, card):
        job_id = card.encrypt_job_id
        self.calls.append(("click", job_id))
        attempt = self.click_counts.get(job_id, 0)
        self.click_counts[job_id] = attempt + 1
        errors = self._click_errors.get(job_id, [])
        if attempt < len(errors) and errors[attempt] is not None:
            raise errors[attempt]
        batches = self._click_packets.get(job_id, [])
        if attempt < len(batches):
            self._queue.extend(batches[attempt])

    def scroll_down(self, pixel):
        self.calls.append(("scroll", pixel))
        if self._scroll_cards:
            self._cards = self._scroll_cards.pop(0)


class FakeProgress:
    def __init__(self, *, actions=()):
        self.details = []
        self.failures = []
        self.events = []
        self.discoveries = []
        self.started = []
        self._actions = list(actions)

    def detail_succeeded(self, task_url, job_id, detail):
        self.details.append((task_url, job_id, detail))

    def detail_failed(self, failure):
        self.failures.append(failure)

    def detail_started(
        self, task_url, job_id, attempt, list_page, scroll_round, card_index
    ):
        self.started.append(
            (
                task_url,
                job_id,
                attempt,
                list_page,
                scroll_round,
                card_index,
            )
        )

    def emit(self, event):
        self.events.append(event)

    def jobs_discovered(self, job_ids, has_more):
        self.discoveries.append((tuple(job_ids), has_more))

    def desired_action(self):
        if self._actions:
            return self._actions.pop(0)
        return None


def list_packet(job_ids, *, has_more=False):
    return FakePacket(
        LIST_URL,
        {
            "zpData": {
                "jobList": [{"encryptJobId": job_id} for job_id in job_ids],
                "hasMore": has_more,
            }
        },
    )


def detail_packet(job_id, description="详情"):
    return FakePacket(
        DETAIL_URL,
        {
            "zpData": {
                "jobInfo": {
                    "encryptJobId": job_id,
                    "postDescription": description,
                    "jobName": "Python 开发",
                }
            }
        },
    )


def card(job_id):
    from jobCollection.jobCollection.boss.workflow import card_from_attributes

    return card_from_attributes({"href": f"/job_detail/{job_id}.html"})


def test_detail_payload_parser_validates_id_and_extracts_description():
    import pytest

    from jobCollection.jobCollection.boss.parsers import parse_boss_job_detail

    detail = parse_boss_job_detail(detail_packet("job-1", "  第一行\n 第二行 ").body)

    assert detail.encrypt_job_id == "job-1"
    assert detail.description == "第一行\n第二行"
    assert detail.data["jobName"] == "Python 开发"

    with pytest.raises(ValueError, match="encryptJobId"):
        parse_boss_job_detail({"zpData": {"jobInfo": {"postDescription": "详情"}}})
    with pytest.raises(ValueError, match="description"):
        parse_boss_job_detail({"zpData": {"jobInfo": {"encryptJobId": "job-1"}}})


def test_rich_progress_receives_complete_list_records_without_breaking_legacy_port():
    from jobCollection.jobCollection.boss.workflow import (
        BossBrowserWorkflow,
        WorkflowConfig,
    )

    class RichProgress(FakeProgress):
        def __init__(self):
            super().__init__()
            self.list_payloads = []

        def list_jobs_discovered(
            self, task_url, jobs, has_more, list_page, scroll_round
        ):
            self.list_payloads.append(
                (task_url, tuple(jobs), has_more, list_page, scroll_round)
            )

    raw_job = {
        "encryptJobId": "job-1",
        "jobName": "Python developer",
        "encryptBrandId": "brand-1",
    }
    browser = FakeBrowser(
        navigate_packets=[
            FakePacket(
                LIST_URL,
                {"zpData": {"jobList": [raw_job], "hasMore": False}},
            )
        ]
    )
    progress = RichProgress()

    BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert progress.list_payloads == [(TASK_URL, (raw_job,), False, 1, 0)]
    assert progress.discoveries == []


def test_card_adapter_extracts_id_from_data_attribute_or_href():
    from jobCollection.jobCollection.boss.workflow import card_from_attributes

    assert card_from_attributes(
        {"data-encrypt-job-id": "from-data", "href": "/job_detail/ignored.html"}
    ).encrypt_job_id == "from-data"
    assert card_from_attributes(
        {"href": "https://www.zhipin.com/job_detail/from-href.html?ka=search_list_jname_1"}
    ).encrypt_job_id == "from-href"
    assert card_from_attributes({"href": "/about"}) is None


def test_listener_starts_once_before_navigation_and_interleaved_packets_do_not_cross_assign():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("job-1")],
        navigate_packets=[list_packet(["job-1"], has_more=False)],
        click_packets={
            "job-1": [[detail_packet("other", "错误详情"), list_packet(["job-1"]), detail_packet("job-1", "正确详情")]]
        },
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert browser.calls[0][0] == "listen"
    assert browser.calls[1] == ("navigate", TASK_URL)
    assert [call for call in browser.calls if call[0] == "listen"] == [browser.calls[0]]
    assert [(job_id, detail.description) for _, job_id, detail in progress.details] == [
        ("job-1", "正确详情")
    ]
    assert result.completed is True


def test_checkpoint_done_jobs_are_not_clicked():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("done"), card("new")],
        navigate_packets=[list_packet(["done", "new"])],
        click_packets={"new": [[detail_packet("new")]]},
    )
    progress = FakeProgress()

    BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL, done_job_ids={"done"})

    assert ("click", "done") not in browser.calls
    assert browser.click_counts == {"new": 1}


def test_checkpoint_done_jobs_are_terminal_in_incomplete_reason():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("done")],
        navigate_packets=[list_packet(["done"], has_more=False)],
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=2, max_scroll_rounds=1),
    ).run(TASK_URL, done_job_ids={"done"})

    assert result.incomplete_reason == "scroll_limit_reached"


def test_detail_retries_three_times_then_records_structured_failure():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("broken")],
        navigate_packets=[list_packet(["broken"])],
        click_packets={"broken": [[], [], []]},
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1, max_detail_attempts=3),
    ).run(TASK_URL)

    assert browser.click_counts == {"broken": 3}
    assert progress.started == [
        (TASK_URL, "broken", 1, 1, 0, 0),
        (TASK_URL, "broken", 2, 1, 0, 0),
        (TASK_URL, "broken", 3, 1, 0, 0),
    ]
    assert len(progress.failures) == 1
    failure = progress.failures[0]
    assert (failure.task_url, failure.job_id, failure.attempt) == (TASK_URL, "broken", 3)
    assert failure.error == "matching detail packet not received"
    assert result.detail_failed_count == 1


def test_detail_click_exceptions_retry_twice_then_succeed():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("flaky")],
        navigate_packets=[list_packet(["flaky"], has_more=False)],
        click_packets={"flaky": [[], [], [detail_packet("flaky")]]},
        click_errors={
            "flaky": [RuntimeError("click one"), OSError("click two"), None],
        },
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1, max_detail_attempts=3),
    ).run(TASK_URL)

    assert result.detail_success_count == 1
    assert browser.click_counts == {"flaky": 3}
    assert progress.started == [
        (TASK_URL, "flaky", 1, 1, 0, 0),
        (TASK_URL, "flaky", 2, 1, 0, 0),
        (TASK_URL, "flaky", 3, 1, 0, 0),
    ]
    assert progress.failures == []


def test_detail_drain_exceptions_retry_twice_then_succeed():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("flaky")],
        navigate_packets=[list_packet(["flaky"], has_more=False)],
        click_packets={"flaky": [[], [], [detail_packet("flaky")]]},
        # The first drain belongs to initial list discovery.
        drain_errors=[None, TimeoutError("drain one"), OSError("drain two"), None],
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1, max_detail_attempts=3),
    ).run(TASK_URL)

    assert result.detail_success_count == 1
    assert browser.click_counts == {"flaky": 3}
    assert progress.failures == []


def test_three_browser_io_exceptions_record_one_detailed_failure():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("broken")],
        navigate_packets=[list_packet(["broken"], has_more=False)],
        click_errors={
            "broken": [
                RuntimeError("temporary one"),
                RuntimeError("temporary two"),
                RuntimeError("temporary three"),
            ]
        },
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1, max_detail_attempts=3),
    ).run(TASK_URL)

    assert result.detail_failed_count == 1
    assert len(progress.failures) == 1
    failure = progress.failures[0]
    assert (failure.task_url, failure.job_id, failure.attempt) == (TASK_URL, "broken", 3)
    assert failure.error == "RuntimeError: temporary three"


def test_progress_exception_is_not_misclassified_as_detail_retry():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow

    class BrokenProgress(FakeProgress):
        def detail_succeeded(self, task_url, job_id, detail):
            raise LookupError("control persistence failed")

    browser = FakeBrowser(
        cards=[card("one")],
        navigate_packets=[list_packet(["one"], has_more=False)],
        click_packets={"one": [[detail_packet("one")]]},
    )
    progress = BrokenProgress()

    import pytest

    with pytest.raises(LookupError, match="control persistence failed"):
        BossBrowserWorkflow(browser, progress).run(TASK_URL)

    assert browser.click_counts == {"one": 1}
    assert progress.failures == []


def test_click_exception_with_page_risk_pauses_without_retry_or_failure():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    class RiskClickBrowser(FakeBrowser):
        def __init__(self, risk_url, **kwargs):
            super().__init__(**kwargs)
            self.risk_url = risk_url

        def click(self, card):
            job_id = card.encrypt_job_id
            self.calls.append(("click", job_id))
            self.click_counts[job_id] = self.click_counts.get(job_id, 0) + 1
            self.current_url = self.risk_url
            raise TimeoutError("click interrupted by risk page")

    for risk_url, reason in (
        ("https://www.zhipin.com/web/user/safe?captcha=1", "captcha"),
        ("https://www.zhipin.com/web/user/login", "login_expired"),
    ):
        browser = RiskClickBrowser(
            risk_url,
            cards=[card("one")],
            navigate_packets=[list_packet(["one"], has_more=False)],
        )
        progress = FakeProgress()

        result = BossBrowserWorkflow(
            browser,
            progress,
            WorkflowConfig(max_detail_attempts=3),
        ).run(TASK_URL)

        assert result.pause_reason == reason
        assert browser.click_counts == {"one": 1}
        assert result.detail_failed_count == 0
        assert progress.failures == []


def test_drain_exception_with_page_risk_pauses_without_retry_or_failure():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    class RiskDrainBrowser(FakeBrowser):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.drain_count = 0

        def drain_packets(self, timeout):
            self.drain_count += 1
            if self.drain_count == 2:
                self.current_url = "https://www.zhipin.com/web/user/safe?captcha=1"
                raise TimeoutError("drain interrupted by captcha")
            return super().drain_packets(timeout)

    browser = RiskDrainBrowser(
        cards=[card("one")],
        navigate_packets=[list_packet(["one"], has_more=False)],
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(max_detail_attempts=3),
    ).run(TASK_URL)

    assert result.pause_reason == "captcha"
    assert browser.click_counts == {"one": 1}
    assert result.detail_failed_count == 0
    assert progress.failures == []


def test_scrolling_finishes_only_after_stable_cards_and_has_more_false():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("one")],
        navigate_packets=[list_packet(["one"], has_more=True)],
        click_packets={"one": [[detail_packet("one")]], "two": [[detail_packet("two")]]},
        scroll_cards=[[card("one"), card("two")], [card("one"), card("two")], [card("one"), card("two")]],
    )
    original_scroll = browser.scroll_down

    def scroll_and_queue(pixel):
        original_scroll(pixel)
        if len([call for call in browser.calls if call[0] == "scroll"]) == 2:
            browser._queue.append(list_packet(["one", "two"], has_more=False))

    browser.scroll_down = scroll_and_queue
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=2, max_scroll_rounds=6),
    ).run(TASK_URL)

    assert result.completed is True
    assert browser.click_counts == {"one": 1, "two": 1}
    assert len([call for call in browser.calls if call[0] == "scroll"]) == 3


def test_captcha_causes_pause_required_and_stops_without_retrying():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(cards=[card("job-1")])
    browser.current_url = "https://www.zhipin.com/web/user/safe?captcha=1"
    progress = FakeProgress()

    result = BossBrowserWorkflow(browser, progress, WorkflowConfig()).run(TASK_URL)

    assert result.pause_required is True
    assert result.pause_reason == "captcha"
    assert progress.events[-1].kind == "pause_required"
    assert progress.events[-1].reason == "captcha"
    assert browser.click_counts == {}


def test_login_redirect_causes_pause_required():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow

    browser = FakeBrowser()
    browser.current_url = "https://www.zhipin.com/web/user/login?ka=header-login"
    progress = FakeProgress()

    result = BossBrowserWorkflow(browser, progress).run(TASK_URL)

    assert result.pause_required is True
    assert result.pause_reason == "login_expired"


def test_http_risk_and_consecutive_empty_list_packets_require_pause():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    for packets, reason, empty_limit in (
        ([FakePacket(LIST_URL, {}, status=429)], "http_429", 3),
        ([FakePacket(LIST_URL, {}), FakePacket(LIST_URL, {})], "empty_packets", 2),
    ):
        browser = FakeBrowser(navigate_packets=packets)
        progress = FakeProgress()
        result = BossBrowserWorkflow(
            browser,
            progress,
            WorkflowConfig(empty_packet_limit=empty_limit),
        ).run(TASK_URL)
        assert result.pause_required is True
        assert result.pause_reason == reason


def test_risk_during_detail_click_keeps_job_pending_instead_of_final_failure():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("job-1")],
        navigate_packets=[list_packet(["job-1"])],
        click_packets={"job-1": [[FakePacket(DETAIL_URL, {}, status=429)]]},
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert result.pause_required is True
    assert result.detail_failed_count == 0
    assert progress.failures == []


def test_api_discovered_job_without_dom_card_never_completes():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("visible")],
        navigate_packets=[list_packet(["visible", "api-only"], has_more=False)],
        click_packets={"visible": [[detail_packet("visible")]]},
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=2),
    ).run(TASK_URL)

    assert result.completed is False
    assert result.incomplete_reason == "unprocessed_list_jobs"
    assert len([call for call in browser.calls if call[0] == "scroll"]) == 2
    assert browser.click_counts == {"visible": 1}


def test_interleaved_detail_for_later_list_job_is_reused_within_same_run():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("a"), card("b")],
        navigate_packets=[list_packet(["a", "b"], has_more=False)],
        click_packets={
            "a": [[detail_packet("b", "B detail"), detail_packet("a", "A detail")]],
        },
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert result.completed is True
    assert [(job_id, detail.description) for _, job_id, detail in progress.details] == [
        ("a", "A detail"),
        ("b", "B detail"),
    ]
    assert browser.click_counts == {"a": 1}


def test_reusing_workflow_clears_detail_cache_and_list_state_between_runs():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("a")],
        navigate_packets=[list_packet(["a"], has_more=False)],
        click_packets={
            "a": [[detail_packet("stale", "old run"), detail_packet("a")]],
        },
    )
    progress = FakeProgress()
    workflow = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1, max_detail_attempts=1),
    )
    workflow.run(TASK_URL)

    browser._cards = [card("stale")]
    browser._navigate_packets = [list_packet(["stale"], has_more=False)]
    browser._click_packets = {"stale": [[]]}
    second = workflow.run(TASK_URL + "&second=1")

    assert second.list_seen_count == 1
    assert [job_id for _, job_id, _ in progress.details] == ["a"]
    assert progress.failures[-1].job_id == "stale"


def test_list_discovery_is_reported_with_optional_has_more():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("one")],
        navigate_packets=[list_packet(["one"], has_more=True)],
        click_packets={"one": [[detail_packet("one")]]},
    )
    progress = FakeProgress()

    BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert progress.discoveries == [(("one",), True)]


def test_operator_pause_at_card_boundary_does_not_click_next_job():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        cards=[card("a"), card("b")],
        navigate_packets=[list_packet(["a", "b"], has_more=False)],
        click_packets={"a": [[detail_packet("a")]], "b": [[detail_packet("b")]]},
    )
    progress = FakeProgress(actions=[None, "pause"])

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert result.pause_required is True
    assert result.pause_reason == "operator_pause"
    assert browser.click_counts == {"a": 1}


def test_operator_stop_at_scroll_boundary_never_completes():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        navigate_packets=[list_packet([], has_more=False)],
    )
    progress = FakeProgress(actions=["stop"])

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=2),
    ).run(TASK_URL)

    assert result.completed is False
    assert result.incomplete_reason == "operator_stop"
    assert not [call for call in browser.calls if call[0] == "scroll"]


def test_list_parser_keeps_unknown_has_more_and_rejects_non_list_jobs():
    from jobCollection.jobCollection.boss.parsers import (
        extract_jobs_and_has_more,
        is_job_list_payload,
    )

    jobs = [{"encryptJobId": "one"}]
    for raw, expected in (
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("FALSE", False),
        ("unknown", None),
    ):
        assert extract_jobs_and_has_more(
            {"zpData": {"jobList": jobs, "hasMore": raw}}
        ) == (jobs, expected)

    assert extract_jobs_and_has_more({"zpData": {"jobList": jobs}}) == (jobs, None)
    invalid = {"zpData": {"jobList": {"encryptJobId": "one"}, "hasMore": False}}
    assert is_job_list_payload(invalid) is False
    assert extract_jobs_and_has_more(invalid) == ([], None)


def test_unknown_has_more_does_not_end_workflow():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    packet = list_packet([])
    del packet.body["zpData"]["hasMore"]
    browser = FakeBrowser(navigate_packets=[packet])
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(stable_rounds=1, max_scroll_rounds=2),
    ).run(TASK_URL)

    assert result.completed is False
    assert len([call for call in browser.calls if call[0] == "scroll"]) == 2


def test_packet_risks_are_aggregated_before_emitting_highest_priority_reason():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow

    browser = FakeBrowser(
        navigate_packets=[
            FakePacket(LIST_URL, {}, status=403),
            FakePacket(LIST_URL, {}, status=429),
        ]
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(browser, progress).run(TASK_URL)

    assert result.pause_reason == "http_429"
    assert [event.reason for event in progress.events] == ["http_429"]


def test_valid_list_packet_breaks_consecutive_empty_packet_risk():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow, WorkflowConfig

    browser = FakeBrowser(
        navigate_packets=[
            FakePacket(LIST_URL, {}),
            FakePacket(LIST_URL, {}),
            list_packet([], has_more=False),
        ]
    )
    progress = FakeProgress()

    result = BossBrowserWorkflow(
        browser,
        progress,
        WorkflowConfig(empty_packet_limit=2, stable_rounds=1, max_scroll_rounds=1),
    ).run(TASK_URL)

    assert result.pause_required is False


def test_page_and_packet_risks_emit_only_final_captcha_reason():
    from jobCollection.jobCollection.boss.workflow import BossBrowserWorkflow

    browser = FakeBrowser(navigate_packets=[FakePacket(LIST_URL, {}, status=429)])
    browser.current_url = "https://www.zhipin.com/web/user/safe?captcha=1"
    progress = FakeProgress()

    result = BossBrowserWorkflow(browser, progress).run(TASK_URL)

    assert result.pause_reason == "captcha"
    assert [event.reason for event in progress.events] == ["captcha"]
