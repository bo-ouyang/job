"""Shared terminal lifecycle for legacy ``AiTask`` Celery work."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping, Optional


logger = logging.getLogger(__name__)


class AiTaskLifecycle:
    """Coordinate persisted task state, message-center notification, and WS events.

    Task modules provide their existing sync/async adapters.  This keeps the
    legacy task names and payloads stable while making the terminal ordering
    explicit and shared.
    """

    def __init__(
        self,
        *,
        persist_completed: Callable[..., bool],
        persist_failed: Callable[..., bool],
        save_notification: Callable[..., Optional[Mapping[str, Any]]],
        enqueue_notification: Callable[..., None],
        publish_event: Callable[[int, str, dict], None],
        feature_display: Callable[[str], str],
        record_metrics: Callable[..., None],
    ) -> None:
        self._persist_completed = persist_completed
        self._persist_failed = persist_failed
        self._save_notification = save_notification
        self._enqueue_notification = enqueue_notification
        self._publish_event = publish_event
        self._feature_display = feature_display
        self._record_metrics = record_metrics

    def complete(
        self,
        *,
        user_id: int,
        feature_key: str,
        celery_task_id: str,
        result_data: str,
        started_at: float = None,
        request_params: dict = None,
        charge_amount: float = 0.0,
    ) -> dict:
        """Persist success before exposing it through any user-facing channel."""
        execution_time = self._execution_time(started_at)
        persisted = self._persist_completed(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            result_data=result_data,
            started_at=started_at,
            request_params=request_params,
            charge_amount=charge_amount,
        )
        if persisted is not True:
            raise RuntimeError(
                f"AI task result was not persisted: task_id={celery_task_id}"
            )

        self._record_metrics_best_effort(
            status="completed",
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            execution_time=execution_time,
        )
        return self._notify(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status="completed",
            execution_time=execution_time,
        )

    def fail(
        self,
        *,
        user_id: int,
        feature_key: str,
        celery_task_id: str,
        error_message: str,
        started_at: float = None,
    ) -> bool:
        """Persist failure before emitting the matching generic terminal event."""
        execution_time = self._execution_time(started_at)
        persisted = self._persist_failed(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            error_message=error_message,
            started_at=started_at,
        )
        if persisted is not True:
            return False

        self._record_metrics_best_effort(
            status="failed",
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            execution_time=execution_time,
        )
        self._notify(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status="failed",
            execution_time=execution_time,
            error_message=error_message,
        )
        return True

    @staticmethod
    def _execution_time(started_at: float) -> Optional[float]:
        return round(time.time() - started_at, 2) if started_at else None

    def _record_metrics_best_effort(
        self,
        *,
        status: str,
        feature_key: str,
        celery_task_id: str,
        execution_time: Optional[float],
    ) -> None:
        """Keep observability failures outside the persisted task lifecycle."""
        try:
            self._record_metrics(
                status=status,
                feature_key=feature_key,
                execution_time=execution_time,
            )
        except Exception:
            logger.warning(
                "ai task metrics recording failed: task_id=%s feature=%s status=%s",
                celery_task_id,
                feature_key,
                status,
                exc_info=True,
            )

    def _notify(
        self,
        *,
        user_id: int,
        feature_key: str,
        celery_task_id: str,
        status: str,
        execution_time: float,
        error_message: str = None,
    ) -> dict:
        message_record = self._save_notification(
            user_id=user_id,
            feature_key=feature_key,
            celery_task_id=celery_task_id,
            status=status,
            execution_time=execution_time,
            error_message=error_message,
        )
        if message_record:
            message_text = message_record["content"]
            message_id = message_record["message_id"]
        else:
            self._enqueue_notification(
                user_id=user_id,
                feature_key=feature_key,
                celery_task_id=celery_task_id,
                status=status,
                execution_time=execution_time,
                error_message=error_message,
            )
            message_text = f"Your {self._feature_display(feature_key)} task has {status}"
            message_id = None

        event_data = {
            "task_id": celery_task_id,
            "feature_key": feature_key,
            "status": status,
            "execution_time": execution_time,
            "message": message_text,
            "message_id": message_id,
        }
        if error_message is not None:
            event_data["error"] = error_message
        self._publish_event(user_id, f"ai_task_{status}", event_data)
        return event_data
