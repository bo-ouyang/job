import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from common.databases.models import AgentConversation, AgentMessage, AgentRun, CareerProfile


def load_agent_schema_module():
    path = Path(__file__).parents[1] / "jobCollectionWebApi" / "schemas" / "agent_schema.py"
    spec = importlib.util.spec_from_file_location("agent_schema_batch1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_tables_have_owner_scoped_keys():
    assert AgentConversation.__table__.c.user_id.foreign_keys
    assert AgentMessage.__table__.c.user_id.foreign_keys
    assert AgentRun.__table__.c.user_id.foreign_keys
    assert CareerProfile.__table__.c.user_id.foreign_keys


def test_agent_run_status_columns_are_persisted():
    columns = AgentRun.__table__.c
    assert columns.status.nullable is False
    assert columns.step_count.nullable is False
    assert columns.tool_call_count.nullable is False


def test_agent_message_schema_rejects_empty_content():
    schema = load_agent_schema_module()
    try:
        schema.AgentMessageCreate(content="")
    except ValueError:
        return
    raise AssertionError("empty agent messages must be rejected")


def test_agent_profile_schema_accepts_structured_fields():
    schema = load_agent_schema_module()
    profile = schema.CareerProfileUpdate(
        skills=[{"name": "SQL", "confirmed": True}],
        goals={"target_role": "数据分析师"},
    )
    assert profile.skills[0]["name"] == "SQL"
    assert profile.goals["target_role"] == "数据分析师"
