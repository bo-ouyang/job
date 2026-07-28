import asyncio
import time
from typing import Any, Dict, Type, TypeVar

from pydantic import BaseModel

from agent.errors import (
    LLMConfigurationError,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from config import settings
from core.circuit_breaker import CircuitBreakerOpen, ai_circuit_breaker
from core.metrics import ai_call_duration, ai_calls_total


SchemaType = TypeVar("SchemaType", bound=BaseModel)


class LLMClient:
    def __init__(self, timeout_seconds: int = 20, max_output_tokens: int = 1200):
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    def _ensure_configured(self) -> None:
        provider = str(settings.AI_PROVIDER or "").strip().lower()
        key = str(settings.AI_API_KEY or "").strip()
        if provider == "mock":
            raise LLMConfigurationError("Agent Runtime 禁止使用生产 Mock 模型")
        if not key or key.lower() in {"your-api-key", "test", "mock"}:
            raise LLMConfigurationError("Agent LLM API Key 未配置")

    def _build_model(self, temperature: float):
        from langchain_openai import ChatOpenAI

        self._ensure_configured()
        kwargs: Dict[str, Any] = {
            "model": settings.AI_MODEL,
            "api_key": settings.AI_API_KEY,
            "temperature": temperature,
            "timeout": self.timeout_seconds,
            "max_retries": 1,
            "max_tokens": self.max_output_tokens,
        }
        base_url = settings.AI_BASE_URL.rstrip("/")
        try:
            return ChatOpenAI(**kwargs, base_url=base_url)
        except TypeError:
            return ChatOpenAI(**kwargs, openai_api_base=base_url)

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        async def call():
            model = self._build_model(temperature=0.2)
            response = await model.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            )
            content = response.content
            if isinstance(content, str):
                return content.strip()
            return str(content).strip()

        return await self._guarded_call("agent_text", call)

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: Type[SchemaType],
    ) -> SchemaType:
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        async def call():
            model = self._build_model(temperature=0.1)
            parser = PydanticOutputParser(pydantic_object=schema)
            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        system_prompt
                        + "\n\n{format_instructions}\n只返回合法 JSON，不输出 Markdown。",
                    ),
                    ("user", "{query}"),
                ]
            )
            chain = prompt | model | parser
            try:
                result = await chain.ainvoke(
                    {
                        "query": user_prompt,
                        "format_instructions": parser.get_format_instructions(),
                    }
                )
            except Exception as exc:
                raise LLMStructuredOutputError("模型未返回有效的结构化结果") from exc
            return result

        result = await self._guarded_call("agent_json", call)
        if not isinstance(result, schema):
            raise LLMStructuredOutputError("结构化结果类型不正确")
        return result

    async def _guarded_call(self, metric_name: str, call):
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                ai_circuit_breaker.call(call),
                timeout=self.timeout_seconds,
            )
            ai_calls_total.labels(method=metric_name, status="success").inc()
            return result
        except asyncio.TimeoutError as exc:
            ai_calls_total.labels(method=metric_name, status="timeout").inc()
            raise LLMTimeoutError("Agent LLM 调用超时") from exc
        except CircuitBreakerOpen as exc:
            ai_calls_total.labels(method=metric_name, status="circuit_open").inc()
            raise LLMUnavailableError("Agent LLM 熔断保护中") from exc
        except (LLMConfigurationError, LLMStructuredOutputError):
            ai_calls_total.labels(method=metric_name, status="failure").inc()
            raise
        except Exception as exc:
            ai_calls_total.labels(method=metric_name, status="failure").inc()
            raise LLMUnavailableError("Agent LLM 暂时不可用") from exc
        finally:
            ai_call_duration.labels(method=metric_name).observe(time.monotonic() - started)


llm_client = LLMClient(
    timeout_seconds=settings.AGENT_LLM_TIMEOUT_SECONDS,
    max_output_tokens=settings.AGENT_MAX_OUTPUT_TOKENS,
)
