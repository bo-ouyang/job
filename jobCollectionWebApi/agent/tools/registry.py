"""Agent 工具注册表：模型只能发现和调用这里注册的工具。"""

from typing import Dict, List

from .base import AgentTool, ToolContext
from .schemas import ToolResult


class AgentToolRegistry:
    """按唯一名称保存工具，并向规划器公开受控 JSON Schema。"""

    def __init__(self):
        """创建空注册表。"""

        self._tools: Dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """注册工具；重复名称直接报错，避免后注册实现静默覆盖前者。"""

        if tool.name in self._tools:
            raise ValueError(f"duplicate Agent tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        """获取已注册工具；未知名称抛出 KeyError。"""

        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown Agent tool: {name}")
        return tool

    def names(self) -> List[str]:
        """返回排序后的工具名称，保证提示词和测试输出稳定。"""

        return sorted(self._tools)

    def definitions(self) -> List[dict]:
        """生成交给规划模型的名称、说明和输入 JSON Schema。"""

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    async def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolResult:
        """按名称调用工具；未知工具返回安全失败结果而不是执行任意代码。"""

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(
                error_code="UNKNOWN_TOOL",
                warning="请求的分析能力不存在",
            )
        return await tool.invoke(arguments, context)


def build_default_tool_registry() -> AgentToolRegistry:
    """构建生产默认注册表，并显式列出全部可用市场数据能力。"""

    from .analysis_tools import (
        CompareCitiesTool,
        CompareIndustriesTool,
        GetMajorDirectionsTool,
        GetMarketOverviewTool,
        GetSkillDemandTool,
    )
    from .job_tools import SearchJobsTool

    registry = AgentToolRegistry()
    for tool in (
        SearchJobsTool(),
        GetMarketOverviewTool(),
        GetSkillDemandTool(),
        GetMajorDirectionsTool(),
        CompareCitiesTool(),
        CompareIndustriesTool(),
    ):
        registry.register(tool)
    return registry


# 应用进程共享的只读默认注册表；各工具本身不保存单次请求状态。
agent_tool_registry = build_default_tool_registry()
