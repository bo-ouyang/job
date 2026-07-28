from typing import Dict, List

from .base import AgentTool, ToolContext
from .schemas import ToolResult


class AgentToolRegistry:
    def __init__(self):
        self._tools: Dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate Agent tool: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"unknown Agent tool: {name}")
        return tool

    def names(self) -> List[str]:
        return sorted(self._tools)

    def definitions(self) -> List[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in (self._tools[name] for name in self.names())
        ]

    async def invoke(self, name: str, arguments: dict, context: ToolContext) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(
                error_code="UNKNOWN_TOOL",
                warning="请求的分析能力不存在",
            )
        return await tool.invoke(arguments, context)


def build_default_tool_registry() -> AgentToolRegistry:
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


agent_tool_registry = build_default_tool_registry()
