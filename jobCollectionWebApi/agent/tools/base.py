"""所有 Agent 数据工具共享的抽象接口和调用保护。"""

import asyncio
from dataclasses import dataclass
from typing import Generic, Type, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import sys_logger as logger
from services.market.errors import MarketResolutionError
from .schemas import ToolResult


InputType = TypeVar("InputType", bound=BaseModel)


@dataclass
class ToolContext:
    """工具执行所需的可信服务端上下文，不允许由模型自行提供。"""

    db: AsyncSession
    user_id: int


class AgentTool(Generic[InputType]):
    """受控 Agent 工具的泛型基类。

    子类声明名称、说明和 Pydantic 输入模型，并只实现 ``execute``。外部统一通过
    ``invoke`` 调用，以获得参数校验、独立超时和稳定错误格式。
    """

    name: str
    description: str
    input_model: Type[InputType]
    timeout_seconds: float = 8.0

    async def execute(self, input_data: InputType, context: ToolContext) -> ToolResult:
        """执行已经校验过的工具输入；具体数据查询由子类实现。"""

        raise NotImplementedError

    async def invoke(self, arguments: dict, context: ToolContext) -> ToolResult:
        """校验模型参数并安全调用工具，把预期异常转换为 ToolResult.failure。

        维度解析失败、单工具超时和未知执行错误使用不同 error_code，方便运行时指标
        与前端提示区分；异常不会直接暴露数据库或后端实现细节给模型和用户。
        """

        try:
            input_data = self.input_model.model_validate(arguments)
        except ValidationError:
            return ToolResult.failure(
                error_code="INVALID_TOOL_ARGUMENTS",
                warning="工具参数不完整或格式不正确",
                filters={},
            )

        try:
            return await asyncio.wait_for(
                self.execute(input_data, context),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Agent tool timed out: {self.name}")
            return ToolResult.failure(
                error_code="TOOL_TIMEOUT",
                warning="数据查询超时，请缩小查询范围后重试",
                filters=input_data.model_dump(),
            )
        except MarketResolutionError as exc:
            logger.warning(f"Agent tool dimension resolution failed: tool={self.name}, error={exc}")
            return ToolResult.failure(
                error_code="DIMENSION_RESOLUTION_FAILED",
                warning=f"城市或行业解析失败：{exc}",
                filters=input_data.model_dump(),
            )
        except Exception as exc:
            logger.exception(f"Agent tool failed: tool={self.name}, error={exc}")
            return ToolResult.failure(
                error_code="TOOL_EXECUTION_FAILED",
                warning="数据服务暂时不可用",
                filters=input_data.model_dump(),
            )
