import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[1] / "jobCollectionWebApi"))

from common.databases.models import AgentMessage, AgentRun


def load_agent_schema_module():
    path = Path(__file__).parents[1] / "jobCollectionWebApi" / "schemas" / "agent_schema.py"
    spec = importlib.util.spec_from_file_location("agent_schema_batch2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_run_has_database_idempotency_constraint():
    constraint_names = {constraint.name for constraint in AgentRun.__table__.constraints}
    assert "uq_agent_run_user_conversation_idempotency" in constraint_names
    assert "idempotency_key" in AgentRun.__table__.c
    assert "input_message_id" in AgentRun.__table__.c


def test_snowflake_ids_are_serialized_as_strings():
    schema = load_agent_schema_module()
    run = schema.AgentRunResponse.model_validate(
        SimpleNamespace(
            id=9223372036854775000,
            conversation_id=9223372036854775001,
            user_id=9223372036854775002,
            input_message_id=9223372036854775003,
            status="queued",
            goal=None,
            current_node=None,
            step_count=0,
            tool_call_count=0,
            state_snapshot=None,
            error_code=None,
            error_message=None,
            started_at=None,
            completed_at=None,
            created_at=None,
        )
    )
    assert run.id == "9223372036854775000"
    assert run.input_message_id == "9223372036854775003"


def test_message_metadata_uses_public_metadata_name():
    schema = load_agent_schema_module()
    message = schema.AgentMessageResponse.model_validate(
        SimpleNamespace(
            id=1,
            conversation_id=2,
            user_id=3,
            role="user",
            message_type="text",
            content="hello",
            metadata_json={"source": "test"},
            created_at=None,
        )
    )
    assert message.model_dump(by_alias=True)["metadata"] == {"source": "test"}


def test_message_input_is_linked_to_run_by_foreign_key():
    foreign_keys = AgentRun.__table__.c.input_message_id.foreign_keys
    assert any(foreign_key.target_fullname == "agent_messages.id" for foreign_key in foreign_keys)
    assert AgentMessage.__tablename__ == "agent_messages"


def test_agent_message_has_independent_idempotency_constraint():
    constraint_names = {constraint.name for constraint in AgentMessage.__table__.constraints}
    assert "uq_agent_message_user_conversation_idempotency" in constraint_names
    assert "idempotency_key" in AgentMessage.__table__.c


def test_agent_rollout_is_disabled_and_allowlist_is_stable(monkeypatch):
    from api.v1.endpoints import agent_controller

    monkeypatch.setattr(agent_controller.settings, "AGENT_ENABLED", False)
    monkeypatch.setattr(agent_controller.settings, "AGENT_ROLLOUT_PERCENT", 100)
    monkeypatch.setattr(agent_controller.settings, "AGENT_ROLLOUT_USER_IDS", "42")
    assert not agent_controller._agent_enabled_for_user(42)

    monkeypatch.setattr(agent_controller.settings, "AGENT_ENABLED", True)
    monkeypatch.setattr(agent_controller.settings, "AGENT_ROLLOUT_PERCENT", 0)
    assert agent_controller._agent_enabled_for_user(42)
    assert not agent_controller._agent_enabled_for_user(43)
