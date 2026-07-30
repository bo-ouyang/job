"""规划结果、最终回答和运行快照的 Pydantic 模型。"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# 双重工具白名单：模型计划必须既在此集合中，也已注册到 AgentToolRegistry。
APPROVED_TOOL_NAMES = {
    "search_jobs",
    "get_market_overview",
    "get_skill_demand",
    "get_major_directions",
    "compare_cities",
    "compare_industries",
}


class PlannedToolCall(BaseModel):
    """规划器提出的一次受控工具调用。"""

    name: str = Field(min_length=1, max_length=60)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    """规划阶段的结构化输出。

    ``action`` 为 ``clarify`` 时向用户追问一个高价值问题；为 ``analyze`` 时执行
    ``tools`` 中的调用。``profile_candidates`` 只是模型推测，不能当作已确认资料。
    """

    intent: str = Field(min_length=1, max_length=200)
    action: Literal["clarify", "analyze"]
    profile_candidates: Dict[str, Any] = Field(default_factory=dict)
    missing_information: List[str] = Field(default_factory=list, max_length=5)
    clarification_question: Optional[str] = Field(default=None, max_length=300)
    tools: List[PlannedToolCall] = Field(default_factory=list, max_length=6)
    rationale: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_action(self):
        """保证澄清分支有问题、分析分支有工具，阻止不可执行的计划进入运行时。"""

        if self.action == "clarify" and not self.clarification_question:
            raise ValueError("clarification_question is required for clarify action")
        if self.action == "analyze" and not self.tools:
            raise ValueError("at least one tool is required for analyze action")
        return self


class AgentAnswer(BaseModel):
    """回答阶段的结构化输出，保存结论、差距、行动和证据摘要。"""

    summary: str = Field(min_length=1, max_length=3000)
    directions: List[Dict[str, Any]] = Field(default_factory=list, max_length=5)
    skill_gaps: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    next_actions: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    evidence_summary: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    follow_up_questions: List[str] = Field(default_factory=list, max_length=3)
    disclaimer: str = "内容由 AI 生成，仅供参考，请结合自身情况进行判断。"

    def to_markdown(self) -> str:
        """把结构化答案转换成适合聊天窗口展示和持久化的 Markdown。"""

        lines = [self.summary.strip()]
        if self.directions:
            lines.extend(["", "## 推荐方向"])
            for item in self.directions:
                title = item.get("title") or item.get("name") or "职业方向"
                reason = item.get("reason") or item.get("summary") or ""
                lines.append(f"- **{title}**：{reason}" if reason else f"- **{title}**")
        if self.skill_gaps:
            lines.extend(["", "## 能力差距"])
            for item in self.skill_gaps:
                name = (
                    item.get("name")
                    or item.get("skill")
                    or item.get("title")
                    or item.get("ability")
                )
                advice = (
                    item.get("advice")
                    or item.get("gap")
                    or item.get("reason")
                    or item.get("description")
                )
                if name:
                    lines.append(f"- **{name}**：{advice}" if advice else f"- **{name}**")
                elif advice:
                    lines.append(f"- {advice}")
        if self.next_actions:
            lines.extend(["", "## 下一步行动"])
            for item in self.next_actions:
                title = item.get("title") or item.get("action") or "行动任务"
                lines.append(f"- {title}")
        lines.extend(["", f"> {self.disclaimer}"])
        return "\n".join(lines)


class RuntimeState(BaseModel):
    """可持久化的 AgentRun 检查点。

    每进入一个关键节点都会写入数据库；Celery 重试或进程恢复时可据此判断已完成
    的步骤、累计工具调用次数以及当前证据，前端也能据此展示运行进度。
    """

    run_id: str
    conversation_id: str
    user_id: str
    current_node: str = "load_context"
    step_count: int = 0
    tool_call_count: int = 0
    clarification_count: int = 0
    intent: Optional[str] = None
    profile_candidates: Dict[str, Any] = Field(default_factory=dict)
    plan: Optional[Dict[str, Any]] = None
    tool_summaries: List[Dict[str, Any]] = Field(default_factory=list)
