"""Agent 有限状态机中的节点定义。"""

from enum import Enum


class AgentNode(str, Enum):
    """一次 AgentRun 从读取上下文到完成回答所经历的逻辑节点。"""

    LOAD_CONTEXT = "load_context"
    UNDERSTAND_AND_PLAN = "understand_and_plan"
    CLARIFICATION = "clarification_required"
    EXECUTE_TOOLS = "execute_tools"
    EVALUATE_EVIDENCE = "evaluate_evidence"
    COMPOSE_ANSWER = "compose_answer"
    SAVE_RESULT = "save_result"
    COMPLETED = "completed"


# 正常“直接分析”路径的节点顺序；澄清分支不在这条线性路径中。
AGENT_NODE_ORDER = (
    AgentNode.LOAD_CONTEXT,
    AgentNode.UNDERSTAND_AND_PLAN,
    AgentNode.EXECUTE_TOOLS,
    AgentNode.EVALUATE_EVIDENCE,
    AgentNode.COMPOSE_ANSWER,
    AgentNode.SAVE_RESULT,
    AgentNode.COMPLETED,
)
