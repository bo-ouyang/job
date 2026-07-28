from enum import Enum


class AgentNode(str, Enum):
    LOAD_CONTEXT = "load_context"
    UNDERSTAND_AND_PLAN = "understand_and_plan"
    CLARIFICATION = "clarification_required"
    EXECUTE_TOOLS = "execute_tools"
    EVALUATE_EVIDENCE = "evaluate_evidence"
    COMPOSE_ANSWER = "compose_answer"
    SAVE_RESULT = "save_result"
    COMPLETED = "completed"


AGENT_NODE_ORDER = (
    AgentNode.LOAD_CONTEXT,
    AgentNode.UNDERSTAND_AND_PLAN,
    AgentNode.EXECUTE_TOOLS,
    AgentNode.EVALUATE_EVIDENCE,
    AgentNode.COMPOSE_ANSWER,
    AgentNode.SAVE_RESULT,
    AgentNode.COMPLETED,
)
