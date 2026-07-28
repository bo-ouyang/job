from dataclasses import dataclass

from config import settings


@dataclass(frozen=True)
class AgentPolicies:
    run_timeout_seconds: int = 60
    llm_timeout_seconds: int = 20
    max_tool_calls: int = 6
    max_steps: int = 12
    max_clarifications: int = 2
    max_output_tokens: int = 1200
    max_context_messages: int = 20

    @classmethod
    def from_settings(cls) -> "AgentPolicies":
        return cls(
            run_timeout_seconds=settings.AGENT_RUN_TIMEOUT_SECONDS,
            llm_timeout_seconds=settings.AGENT_LLM_TIMEOUT_SECONDS,
            max_tool_calls=settings.AGENT_MAX_TOOL_CALLS,
            max_steps=settings.AGENT_MAX_STEPS,
            max_clarifications=settings.AGENT_MAX_CLARIFICATIONS,
            max_output_tokens=settings.AGENT_MAX_OUTPUT_TOKENS,
            max_context_messages=settings.AGENT_MAX_CONTEXT_MESSAGES,
        )
