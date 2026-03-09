"""
AI API 调用使用的熔断器模式。

目的：
- 当 AI 服务商不可用、超时或被限流时，快速失败，避免请求继续堆积；
- 阻止下游故障向上游扩散；
- 在冷却时间结束后，允许少量探测流量判断服务是否恢复。

状态流转：

    CLOSED  -> OPEN      连续失败达到阈值
    OPEN    -> HALF_OPEN 冷却时间到期
    HALF_OPEN -> CLOSED  探测成功
    HALF_OPEN -> OPEN    探测失败
"""

import asyncio
import time
from enum import Enum

from core.logger import sys_logger as logger


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpen(Exception):
    """当熔断器处于 OPEN 状态且请求被拒绝时抛出。"""

    def __init__(self, breaker_name: str, retry_after: float):
        self.breaker_name = breaker_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker '{breaker_name}' is OPEN. "
            f"Retry after {retry_after:.0f}s."
        )


class CircuitBreaker:
    """
    适用于异步场景的熔断器。

    使用示例：

        ai_breaker = CircuitBreaker("deepseek", failure_threshold=5, recovery_timeout=60)

        try:
            result = await ai_breaker.call(ai_service._call_llm_with_langchain, prompt, user_prompt)
        except CircuitBreakerOpen:
            # 走降级逻辑 / 返回缓存 / 返回 503
            ...
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 1,
    ):
        """
        熔断器状态机配置说明。

        - failure_threshold: 连续失败多少次后触发熔断 (CLOSED -> OPEN)
        - recovery_timeout: 熔断(OPEN)后需要冷却多久(秒)，才允许请求探活 (OPEN -> HALF_OPEN)
        - success_threshold: HALF_OPEN 阶段连续成功多少次，才真正恢复为 CLOSED
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0
        # 保护状态切换时的一致性，避免并发请求同时修改内部计数和状态。
        self._lock = asyncio.Lock()

    # 对外公开的方法与属性

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, func, *args, **kwargs):
        """
        通过熔断器执行目标异步函数 `func`，例如调用 LLM。

        这里分成两个阶段：
        1. 状态判断阶段（持锁）：
           快速检查当前状态是否允许继续请求。
           如果当前是 OPEN，则直接快速失败，不再访问下游。
        2. 实际执行阶段（无锁）：
           释放状态锁后再发起真实网络请求，避免把所有正常请求串行化。
        """
        async with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                retry_after = self.recovery_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise CircuitBreakerOpen(self.name, max(retry_after, 0))

        # 释放状态锁后再执行真实调用，不阻塞其他协程做状态判断。
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            await self._on_failure(exc)
            raise
        else:
            await self._on_success()
            return result

    def reset(self):
        """手动重置为 CLOSED，常用于配置调整或人工恢复后。"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        logger.info(f"CircuitBreaker[{self.name}] manually reset to CLOSED")

    # 内部状态迁移与计数逻辑

    def _maybe_transition_to_half_open(self):
        """在 OPEN 状态下检查冷却时间是否已到，决定是否切到 HALF_OPEN。"""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
                logger.info(
                    f"CircuitBreaker[{self.name}] OPEN -> HALF_OPEN "
                    f"(after {elapsed:.1f}s)"
                )

    async def _on_success(self):
        """记录一次成功调用，并根据当前状态决定是否恢复。"""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    logger.info(
                        f"CircuitBreaker[{self.name}] HALF_OPEN -> CLOSED"
                    )
            else:
                # 在 CLOSED 状态下，只要有成功就清空连续失败计数。
                self._failure_count = 0

    async def _on_failure(self, exc: Exception):
        """记录一次失败调用，并在达到条件时触发熔断。"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}] HALF_OPEN -> OPEN "
                    f"(probe failed: {exc!r})"
                )
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                logger.warning(
                    f"CircuitBreaker[{self.name}] CLOSED -> OPEN "
                    f"(failures={self._failure_count}, last: {exc!r})"
                )
                # 记录一次熔断事件，供 Prometheus 监控使用。
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


# 全局单例实例

# 主熔断器：用于绝大多数 AI / LLM 调用
ai_circuit_breaker = CircuitBreaker(
    name="ai_llm",
    failure_threshold=5,
    recovery_timeout=60,
)
