from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


APPROVED_TOOL_NAMES = {
    "search_jobs",
    "get_market_overview",
    "get_skill_demand",
    "get_major_directions",
    "compare_cities",
    "compare_industries",
}


class PlannedToolCall(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    intent: str = Field(min_length=1, max_length=200)
    action: Literal["clarify", "analyze"]
    profile_candidates: Dict[str, Any] = Field(default_factory=dict)
    missing_information: List[str] = Field(default_factory=list, max_length=5)
    clarification_question: Optional[str] = Field(default=None, max_length=300)
    tools: List[PlannedToolCall] = Field(default_factory=list, max_length=6)
    rationale: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "clarify" and not self.clarification_question:
            raise ValueError("clarification_question is required for clarify action")
        if self.action == "analyze" and not self.tools:
            raise ValueError("at least one tool is required for analyze action")
        return self


class AgentAnswer(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    directions: List[Dict[str, Any]] = Field(default_factory=list, max_length=5)
    skill_gaps: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    next_actions: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    evidence_summary: List[Dict[str, Any]] = Field(default_factory=list, max_length=10)
    follow_up_questions: List[str] = Field(default_factory=list, max_length=3)
    disclaimer: str = "内容由 AI 生成，仅供参考，请结合自身情况进行判断。"

    def to_markdown(self) -> str:
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
                name = item.get("name") or "待提升能力"
                advice = item.get("advice") or item.get("gap") or ""
                lines.append(f"- **{name}**：{advice}" if advice else f"- **{name}**")
        if self.next_actions:
            lines.extend(["", "## 下一步行动"])
            for item in self.next_actions:
                title = item.get("title") or item.get("action") or "行动任务"
                lines.append(f"- {title}")
        lines.extend(["", f"> {self.disclaimer}"])
        return "\n".join(lines)


class RuntimeState(BaseModel):
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
