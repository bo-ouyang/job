"""Emit bounded, credential-free telemetry for the machine-side Crawler Agent."""

from datetime import datetime, timezone
import json
import math
import os
from typing import Any, Dict, Optional

from scrapy import signals


TELEMETRY_PREFIX = "CRAWLER_EVENT "
MAX_LINE_BYTES = 32768
DENIED_KEYS = {
    "authorization",
    "body",
    "cookie",
    "cookies",
    "headers",
    "password",
    "proxy",
    "response",
    "secret",
    "token",
}


def _safe_scalar(value: Any, *, max_length: int = 1000):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if isinstance(value, str):
        return value[:max_length]
    return None


def _safe_mapping(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result = {}
    for raw_key, value in (values or {}).items():
        key = str(raw_key)[:80]
        lowered = key.casefold()
        if any(denied in lowered for denied in DENIED_KEYS):
            continue
        safe_value = _safe_scalar(value)
        if safe_value is not None:
            result[key] = safe_value
    return result


def serialize_telemetry(
    event_type: str,
    *,
    metrics: Optional[Dict[str, Any]] = None,
    checkpoint: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    level: str = "info",
) -> str:
    event = {
        "eventType": str(event_type)[:50],
        "level": level if level in {"debug", "info", "warning", "error"} else "info",
        "message": str(message)[:4000] if message is not None else None,
        "metrics": _safe_mapping(metrics),
        "checkpoint": _safe_mapping(checkpoint),
        "payload": _safe_mapping(payload),
        "emittedAt": datetime.now(timezone.utc).isoformat(),
    }
    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    line = TELEMETRY_PREFIX + encoded
    if len(line.encode("utf-8")) <= MAX_LINE_BYTES:
        return line
    event["message"] = "telemetry event truncated"
    event["metrics"] = {}
    event["payload"] = {"truncated": True}
    event["checkpoint"] = {}
    encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=str)
    return TELEMETRY_PREFIX + encoded


class CrawlerTelemetryExtension:
    def __init__(self, crawler):
        self.crawler = crawler
        self.run_id = os.getenv("CRAWLER_RUN_ID", "")
        self.worker_id = os.getenv("CRAWLER_WORKER_ID", "")
        self.emit_every = max(1, int(os.getenv("CRAWLER_TELEMETRY_EVERY", "10")))
        self.items_scraped = 0
        self.responses_received = 0
        self.pages_processed = 0
        self.errors = 0

    @classmethod
    def from_crawler(cls, crawler):
        extension = cls(crawler)
        crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(extension.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(extension.response_received, signal=signals.response_received)
        crawler.signals.connect(extension.spider_error, signal=signals.spider_error)
        crawler.signals.connect(extension.spider_closed, signal=signals.spider_closed)
        return extension

    def _metrics(self) -> Dict[str, int]:
        return {
            "itemsScraped": self.items_scraped,
            "responsesReceived": self.responses_received,
            "pagesProcessed": self.pages_processed,
            "errors": self.errors,
        }

    def _checkpoint(self, spider) -> Dict[str, Any]:
        page = getattr(spider, "current_page", None)
        task_id = getattr(spider, "current_task_id", None)
        values = {}
        if isinstance(page, int):
            values["page"] = page
        if isinstance(task_id, int):
            values["taskId"] = task_id
        return values

    def _emit(self, event_type: str, spider, *, message=None, level="info", payload=None):
        print(
            serialize_telemetry(
                event_type,
                metrics=self._metrics(),
                checkpoint=self._checkpoint(spider),
                payload={
                    "spider": getattr(spider, "name", "unknown"),
                    "runId": self.run_id,
                    "workerId": self.worker_id,
                    **(payload or {}),
                },
                message=message,
                level=level,
            ),
            flush=True,
        )

    def spider_opened(self, spider):
        self._emit("spider_opened", spider, message="Crawler spider opened")

    def item_scraped(self, item, response, spider):
        self.items_scraped += 1
        page = getattr(spider, "current_page", None)
        if isinstance(page, int):
            self.pages_processed = max(self.pages_processed, page)
        if self.items_scraped % self.emit_every == 0:
            self._emit("progress", spider, message="Crawler progress")

    def response_received(self, response, request, spider):
        self.responses_received += 1
        if self.responses_received % self.emit_every == 0:
            self._emit(
                "progress",
                spider,
                message="Crawler response progress",
                payload={"statusCode": getattr(response, "status", None)},
            )

    def spider_error(self, failure, response, spider):
        self.errors += 1
        self._emit(
            "spider_error",
            spider,
            message=str(getattr(failure, "value", failure))[:1000],
            level="error",
        )

    def spider_closed(self, spider, reason):
        self._emit(
            "spider_closed",
            spider,
            message="Crawler spider closed",
            payload={"reason": str(reason)[:200]},
        )
