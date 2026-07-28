class AgentRuntimeError(Exception):
    code = "AGENT_RUNTIME_ERROR"


class AgentCancelledError(AgentRuntimeError):
    code = "AGENT_CANCELLED"


class AgentDeadlineExceededError(AgentRuntimeError):
    code = "AGENT_DEADLINE_EXCEEDED"


class AgentLimitExceededError(AgentRuntimeError):
    code = "AGENT_LIMIT_EXCEEDED"


class AgentEvidenceUnavailableError(AgentRuntimeError):
    code = "AGENT_EVIDENCE_UNAVAILABLE"


class LLMConfigurationError(AgentRuntimeError):
    code = "AGENT_LLM_NOT_CONFIGURED"


class LLMUnavailableError(AgentRuntimeError):
    code = "AGENT_LLM_UNAVAILABLE"


class LLMTimeoutError(AgentRuntimeError):
    code = "AGENT_LLM_TIMEOUT"


class LLMStructuredOutputError(AgentRuntimeError):
    code = "AGENT_LLM_INVALID_OUTPUT"
