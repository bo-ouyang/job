"""Agent 运行过程中使用的业务异常。

所有异常都带有稳定的 ``code``，任务层可以把内部异常转换成前端可识别的失败原因，
而不需要依赖可能变化的异常文本。
"""


class AgentRuntimeError(Exception):
    """Agent 模块异常的统一基类。"""

    code = "AGENT_RUNTIME_ERROR"


class AgentCancelledError(AgentRuntimeError):
    """运行已被用户取消，或执行租约已失效。"""

    code = "AGENT_CANCELLED"


class AgentDeadlineExceededError(AgentRuntimeError):
    """整次运行或其中一次模型/工具调用超过允许时限。"""

    code = "AGENT_DEADLINE_EXCEEDED"


class AgentLimitExceededError(AgentRuntimeError):
    """步骤数、工具调用数或澄清轮数超过安全上限。"""

    code = "AGENT_LIMIT_EXCEEDED"


class AgentEvidenceUnavailableError(AgentRuntimeError):
    """没有获得足以支撑回答的真实市场数据。"""

    code = "AGENT_EVIDENCE_UNAVAILABLE"


class LLMConfigurationError(AgentRuntimeError):
    """大模型提供商、密钥或模型名称未正确配置。"""

    code = "AGENT_LLM_NOT_CONFIGURED"


class LLMUnavailableError(AgentRuntimeError):
    """大模型服务当前不可用。"""

    code = "AGENT_LLM_UNAVAILABLE"


class LLMTimeoutError(AgentRuntimeError):
    """单次大模型请求超时。"""

    code = "AGENT_LLM_TIMEOUT"


class LLMStructuredOutputError(AgentRuntimeError):
    """模型返回内容无法通过预期的 Pydantic 结构校验。"""

    code = "AGENT_LLM_INVALID_OUTPUT"
