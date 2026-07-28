import asyncio
from dataclasses import dataclass
from typing import Generic, Type, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import sys_logger as logger
from .schemas import ToolResult


InputType = TypeVar("InputType", bound=BaseModel)


@dataclass
class ToolContext:
    db: AsyncSession
    user_id: int


class AgentTool(Generic[InputType]):
    name: str
    description: str
    input_model: Type[InputType]
    timeout_seconds: float = 8.0

    async def execute(self, input_data: InputType, context: ToolContext) -> ToolResult:
        raise NotImplementedError

    async def invoke(self, arguments: dict, context: ToolContext) -> ToolResult:
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
        except Exception as exc:
            logger.exception(f"Agent tool failed: tool={self.name}, error={exc}")
            return ToolResult.failure(
                error_code="TOOL_EXECUTION_FAILED",
                warning="数据服务暂时不可用",
                filters=input_data.model_dump(),
            )
