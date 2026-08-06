"""Pure, synchronous orchestration for one BOSS browser task.

The workflow owns no browser implementation and performs no persistence.  A
real DrissionPage adapter can implement :class:`BrowserPort`; tests use a fake.
Every browser method is invoked serially by the thread calling ``run()``.
"""

from dataclasses import dataclass
import re
import threading
from urllib.parse import parse_qs, urlsplit
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Sequence, Set

from .parsers import (
    BossJobDetail,
    extract_jobs_and_has_more,
    is_job_list_payload,
    parse_boss_job_detail,
)


LIST_TARGETS = ("job/list.json", "joblist.json")
DETAIL_TARGET = "job/detail.json"
LISTENER_TARGETS = LIST_TARGETS + (DETAIL_TARGET,)
_JOB_DETAIL_PATH = re.compile(r"/job_detail/([^/?#]+)\.html(?:[?#]|$)")


@dataclass(frozen=True)
class CardSnapshot:
    encrypt_job_id: str
    attributes: Mapping[str, Any]
    target: Any = None


@dataclass(frozen=True)
class DetailFailure:
    task_url: str
    job_id: str
    attempt: int
    error: str


@dataclass(frozen=True)
class WorkflowEvent:
    kind: str
    task_url: str
    reason: str


@dataclass(frozen=True)
class WorkflowConfig:
    packet_timeout: float = 5.0
    stable_rounds: int = 2
    max_scroll_rounds: int = 100
    max_detail_attempts: int = 3
    empty_packet_limit: int = 3
    scroll_pixel: int = 800

    def __post_init__(self) -> None:
        for name in (
            "stable_rounds",
            "max_scroll_rounds",
            "max_detail_attempts",
            "empty_packet_limit",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")


@dataclass(frozen=True)
class WorkflowResult:
    completed: bool
    incomplete_reason: Optional[str]
    pause_required: bool
    pause_reason: Optional[str]
    list_seen_count: int
    detail_success_count: int
    detail_failed_count: int
    scroll_rounds: int


class BrowserPort(Protocol):
    current_url: str

    def start_listener(self, targets: Sequence[str]) -> None:
        ...

    def navigate(self, url: str) -> None:
        ...

    def drain_packets(self, timeout: float) -> Iterable[Any]:
        ...

    def cards(self) -> Sequence[CardSnapshot]:
        ...

    def click(self, card: CardSnapshot) -> None:
        ...

    def scroll_down(self, pixel: int) -> None:
        ...


class ProgressPort(Protocol):
    def jobs_discovered(
        self, job_ids: Sequence[str], has_more: Optional[bool]
    ) -> None:
        ...

    def desired_action(self) -> Optional[str]:
        ...

    def detail_succeeded(
        self, task_url: str, job_id: str, detail: BossJobDetail
    ) -> None:
        ...

    def detail_failed(self, failure: DetailFailure) -> None:
        ...

    def emit(self, event: WorkflowEvent) -> None:
        ...


def card_from_attributes(
    attributes: Mapping[str, Any], target: Any = None
) -> Optional[CardSnapshot]:
    """Build a card snapshot from stable data attributes or its detail href."""
    for key in ("data-encrypt-job-id", "data-job-id", "data-security-id"):
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            return CardSnapshot(value.strip(), dict(attributes), target)

    href = attributes.get("href")
    if isinstance(href, str):
        match = _JOB_DETAIL_PATH.search(href)
        if match:
            return CardSnapshot(match.group(1), dict(attributes), target)
    return None


class BossBrowserWorkflow:
    """Run list discovery and clicked detail capture through one listener."""

    def __init__(
        self,
        browser: BrowserPort,
        progress: ProgressPort,
        config: Optional[WorkflowConfig] = None,
    ) -> None:
        self.browser = browser
        self.progress = progress
        self.config = config or WorkflowConfig()
        self._owner_thread_id: Optional[int] = None
        self._task_url = ""
        self._has_more: Optional[bool] = None
        self._empty_packet_count = 0
        self._list_job_ids: Set[str] = set()
        self._detail_cache: Dict[str, BossJobDetail] = {}
        self._pause_reason: Optional[str] = None
        self._risk_reasons: Set[str] = set()
        self._stop_requested = False
        self._current_scroll_round = 0
        self._job_list_pages: Dict[str, int] = {}

    def run(
        self, task_url: str, done_job_ids: Optional[Set[str]] = None
    ) -> WorkflowResult:
        self._reset_run_state(task_url)
        done = set(done_job_ids or ())
        failed: Set[str] = set()
        succeeded: Set[str] = set()

        self._call(self.browser.start_listener, LISTENER_TARGETS)
        self._call(self.browser.navigate, task_url)

        stable_count = 0
        previous_discovery_count = 0
        scroll_rounds = 0

        for round_index in range(self.config.max_scroll_rounds + 1):
            self._check_page_risk()
            self._consume_packets()
            self._check_page_risk()
            self._finalize_risk()
            if self._pause_reason:
                break

            cards = [card for card in self._call(self.browser.cards) if card is not None]
            for card_index, card in enumerate(cards):
                if not self._continue_requested():
                    break
                job_id = card.encrypt_job_id
                if job_id in done or job_id in failed or job_id in succeeded:
                    continue
                if self._capture_detail(card, card_index):
                    succeeded.add(job_id)
                elif not self._pause_reason:
                    failed.add(job_id)
                if self._pause_reason or self._stop_requested:
                    break
            if self._pause_reason or self._stop_requested:
                break

            discovered = self._list_job_ids.union(
                card.encrypt_job_id for card in cards
            )
            discovery_count = len(discovered)
            if discovery_count > previous_discovery_count:
                stable_count = 0
            else:
                stable_count += 1
            previous_discovery_count = max(previous_discovery_count, discovery_count)

            if not self._continue_requested():
                break
            terminal_job_ids = done.union(succeeded, failed)
            all_list_jobs_terminal = self._list_job_ids.issubset(terminal_job_ids)
            if (
                self._has_more is False
                and stable_count >= self.config.stable_rounds
                and all_list_jobs_terminal
            ):
                return self._result(True, done, succeeded, failed, scroll_rounds)

            if round_index >= self.config.max_scroll_rounds:
                break
            if not self._continue_requested():
                break
            self._call(self.browser.scroll_down, self.config.scroll_pixel)
            scroll_rounds += 1
            self._current_scroll_round = scroll_rounds

        return self._result(False, done, succeeded, failed, scroll_rounds)

    def _capture_detail(self, card: CardSnapshot, card_index: int) -> bool:
        job_id = card.encrypt_job_id
        cached_detail = self._detail_cache.pop(job_id, None)
        if cached_detail is not None:
            self.progress.detail_succeeded(self._task_url, job_id, cached_detail)
            return True
        last_error = "matching detail packet not received"
        for attempt in range(1, self.config.max_detail_attempts + 1):
            started = getattr(self.progress, "detail_started", None)
            if callable(started):
                started(
                    self._task_url,
                    job_id,
                    attempt,
                    self._job_list_pages.get(job_id, 1),
                    self._current_scroll_round,
                    card_index,
                )
            self._assert_owner_thread()
            try:
                self.browser.click(card)
            except Exception as error:
                last_error = self._format_browser_error(error)
                self._check_page_risk()
                self._finalize_risk()
                if self._pause_reason:
                    return False
                continue
            self._check_page_risk()
            self._assert_owner_thread()
            try:
                packets = self.browser.drain_packets(self.config.packet_timeout)
            except Exception as error:
                last_error = self._format_browser_error(error)
                self._check_page_risk()
                self._finalize_risk()
                if self._pause_reason:
                    return False
                continue
            self._dispatch_packets(packets)
            self._check_page_risk()
            self._finalize_risk()
            if self._pause_reason:
                return False
            detail = self._detail_cache.pop(job_id, None)
            if detail is not None:
                self.progress.detail_succeeded(self._task_url, job_id, detail)
                return True

        self.progress.detail_failed(
            DetailFailure(
                task_url=self._task_url,
                job_id=job_id,
                attempt=self.config.max_detail_attempts,
                error=last_error,
            )
        )
        return False

    def _consume_packets(self) -> None:
        packets = self._call(
            self.browser.drain_packets,
            self.config.packet_timeout,
        )
        self._dispatch_packets(packets)

    def _dispatch_packets(self, packets: Iterable[Any]) -> None:
        for packet in packets:
            url = str(getattr(packet, "url", "") or "")
            response = getattr(packet, "response", None)
            status = getattr(response, "status", None)
            if status in (403, 429):
                self._risk_reasons.add(f"http_{status}")
            body = getattr(response, "body", None)

            if any(target in url for target in LIST_TARGETS):
                self._dispatch_list(body, url)
            elif DETAIL_TARGET in url:
                self._dispatch_detail(body)

    @staticmethod
    def _format_browser_error(error: Exception) -> str:
        return f"{type(error).__name__}: {error}"

    def _dispatch_list(self, body: Any, packet_url: str = "") -> None:
        if not is_job_list_payload(body):
            self._empty_packet_count += 1
            if self._empty_packet_count >= self.config.empty_packet_limit:
                self._risk_reasons.add("empty_packets")
            return

        jobs, has_more = extract_jobs_and_has_more(body)
        self._empty_packet_count = 0
        self._risk_reasons.discard("empty_packets")
        self._has_more = has_more
        page_values = parse_qs(urlsplit(packet_url).query).get("page", [])
        try:
            list_page = max(1, int(page_values[0])) if page_values else 1
        except (TypeError, ValueError):
            list_page = 1
        discovered_ids = []
        for job in jobs:
            job_id = job.get("encryptJobId") if isinstance(job, dict) else None
            if isinstance(job_id, str) and job_id:
                normalized_job_id = job_id.strip()
                if normalized_job_id and normalized_job_id not in discovered_ids:
                    discovered_ids.append(normalized_job_id)
                    self._list_job_ids.add(normalized_job_id)
                    self._job_list_pages.setdefault(normalized_job_id, list_page)
        rich_callback = getattr(self.progress, "list_jobs_discovered", None)
        if callable(rich_callback):
            rich_callback(
                self._task_url,
                tuple(jobs),
                has_more,
                list_page,
                self._current_scroll_round,
            )
        else:
            self.progress.jobs_discovered(tuple(discovered_ids), has_more)

    def _dispatch_detail(self, body: Any) -> None:
        try:
            detail = parse_boss_job_detail(body)
        except ValueError:
            return
        self._detail_cache[detail.encrypt_job_id] = detail

    def _check_page_risk(self) -> None:
        current_url = str(getattr(self.browser, "current_url", "") or "").lower()
        if "captcha" in current_url or "/user/safe" in current_url:
            self._risk_reasons.add("captcha")
        elif "/user/login" in current_url or "/login" in current_url:
            self._risk_reasons.add("login_expired")

    def _finalize_risk(self) -> None:
        if not self._risk_reasons:
            return
        priority = {
            "captcha": 0,
            "login_expired": 1,
            "http_429": 2,
            "http_403": 3,
            "empty_packets": 4,
        }
        reason = min(self._risk_reasons, key=lambda value: priority.get(value, 99))
        self._risk_reasons.clear()
        self._require_pause(reason)

    def _continue_requested(self) -> bool:
        action = self.progress.desired_action()
        if action is None:
            return True
        normalized = str(action).strip().lower()
        if normalized == "pause":
            self._require_pause("operator_pause")
            return False
        if normalized == "stop":
            if not self._stop_requested:
                self._stop_requested = True
                self.progress.emit(
                    WorkflowEvent(
                        kind="stop_requested",
                        task_url=self._task_url,
                        reason="operator_stop",
                    )
                )
            return False
        return True

    def _require_pause(self, reason: str) -> None:
        if self._pause_reason is not None:
            return
        self._pause_reason = reason
        self.progress.emit(
            WorkflowEvent(
                kind="pause_required",
                task_url=self._task_url,
                reason=reason,
            )
        )

    def _result(
        self,
        completed: bool,
        done: Set[str],
        succeeded: Set[str],
        failed: Set[str],
        scroll_rounds: int,
    ) -> WorkflowResult:
        incomplete_reason = None
        if not completed:
            if self._stop_requested:
                incomplete_reason = "operator_stop"
            elif self._pause_reason is not None:
                incomplete_reason = self._pause_reason
            elif self._has_more is False and not self._list_job_ids.issubset(
                done.union(succeeded, failed)
            ):
                incomplete_reason = "unprocessed_list_jobs"
            elif self._has_more is not False:
                incomplete_reason = "list_not_exhausted"
            else:
                incomplete_reason = "scroll_limit_reached"
        return WorkflowResult(
            completed=completed,
            incomplete_reason=incomplete_reason,
            pause_required=self._pause_reason is not None,
            pause_reason=self._pause_reason,
            list_seen_count=len(self._list_job_ids),
            detail_success_count=len(succeeded),
            detail_failed_count=len(failed),
            scroll_rounds=scroll_rounds,
        )

    def _reset_run_state(self, task_url: str) -> None:
        self._owner_thread_id = threading.get_ident()
        self._task_url = task_url
        self._has_more = None
        self._empty_packet_count = 0
        self._list_job_ids.clear()
        self._detail_cache.clear()
        self._pause_reason = None
        self._risk_reasons.clear()
        self._stop_requested = False
        self._current_scroll_round = 0
        self._job_list_pages.clear()

    def _call(self, function: Any, *args: Any) -> Any:
        self._assert_owner_thread()
        return function(*args)

    def _assert_owner_thread(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise RuntimeError("browser calls must stay on the workflow owner thread")
