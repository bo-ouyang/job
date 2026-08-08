import pytest
from pydantic import BaseModel

from agent.errors import LLMUnavailableError
from services import llm_client as llm_module


class ProviderBalanceError(Exception):
    status_code = 402


class ExampleStructuredReply(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_provider_balance_error_has_a_distinct_agent_error_code(monkeypatch):
    async def bypass_circuit_breaker(callback):
        return await callback()

    async def exhausted_provider():
        raise ProviderBalanceError("Insufficient Balance")

    monkeypatch.setattr(llm_module.ai_circuit_breaker, "call", bypass_circuit_breaker)

    with pytest.raises(LLMUnavailableError) as captured:
        await llm_module.LLMClient()._guarded_call("agent_json", exhausted_provider)

    assert captured.value.code == "AGENT_LLM_QUOTA_EXCEEDED"
    assert "余额不足" in str(captured.value)


@pytest.mark.asyncio
async def test_structured_call_preserves_provider_balance_error(monkeypatch):
    from langchain_core.runnables import RunnableLambda

    async def exhausted_provider(_):
        raise ProviderBalanceError("Insufficient Balance")

    client = llm_module.LLMClient()
    monkeypatch.setattr(client, "_build_model", lambda temperature: RunnableLambda(exhausted_provider))

    with pytest.raises(LLMUnavailableError) as captured:
        await client.complete_structured("system", "question", ExampleStructuredReply)

    assert captured.value.code == "AGENT_LLM_QUOTA_EXCEEDED"
