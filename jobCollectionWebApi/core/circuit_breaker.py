"""
Circuit Breaker pattern for AI API calls.

Prevents cascading failures when the AI provider (DeepSeek, etc.) is
down or rate-limited.  Three states:

    CLOSED  ──(N consecutive failures)──▶  OPEN
    OPEN    ──(recovery_timeout elapsed)──▶  HALF_OPEN
    HALF_OPEN ──(success)──▶  CLOSED
    HALF_OPEN ──(failure)──▶  OPEN
"""

import time
import asyncio
from enum import Enum
from core.logger import sys_logger as logger


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """Raised when the circuit is OPEN and calls are rejected."""
    def __init__(self, breaker_name: str, retry_after: float):
        self.breaker_name = breaker_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN. "
            f"Retry after {retry_after:.0f}s."
        )


class CircuitBreaker:
    """
    Async-friendly circuit breaker.

    Usage::

        ai_breaker = CircuitBreaker("deepseek", failure_threshold=5, recovery_timeout=60)

        try:
            result = await ai_breaker.call(ai_service._call_llm_with_langchain, prompt, user_prompt)
        except CircuitBreakerOpen:
            # fallback / return cached / 503
            ...
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        self._lock = asyncio.Lock()

    # ── public ──────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, func, *args, **kwargs):
        """Execute *func* through the circuit breaker."""
        async with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                retry_after = self.recovery_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitBreakerOpen(self.name, max(retry_after, 0))

        # Execute outside the lock so concurrent callers aren't serialised.
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            await self._on_failure(exc)
            raise
        else:
            await self._on_success()
            return result

    def reset(self):
        """Manually reset to CLOSED (e.g. after config change)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info(f"CircuitBreaker[{self.name}] manually reset to CLOSED")

    # ── private ─────────────────────────────────────────────

    def _maybe_transition_to_half_open(self):
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info(
                    f"CircuitBreaker[{self.name}] OPEN → HALF_OPEN "
                    f"(after {elapsed:.1f}s)"
                )

    async def _on_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(
                        f"CircuitBreaker[{self.name}] HALF_OPEN → CLOSED"
                    )
            else:
                # In CLOSED state, a success resets the failure counter.
                self._failure_count = 0

    async def _on_failure(self, exc: Exception):
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}] HALF_OPEN → OPEN "
                    f"(probe failed: {exc!r})"
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}] CLOSED → OPEN "
                    f"(failures={self._failure_count}, last: {exc!r})"
                )
                # Prometheus: record trip event
                try:
                    from core.metrics import circuit_breaker_trips
                    circuit_breaker_trips.labels(breaker_name=self.name).inc()
                except Exception:
                    pass

    def __repr__(self):
        return (
            f"CircuitBreaker(name={self.name!r}, state={self._state.value}, "
            f"failures={self._failure_count})"
        )


# ── Singleton instances ────────────────────────────────────

# Main breaker for all AI / LLM calls
ai_circuit_breaker = CircuitBreaker(
    name="ai_llm",
    failure_threshold=5,
    recovery_timeout=60,
)
