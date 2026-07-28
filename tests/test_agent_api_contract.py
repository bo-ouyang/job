import inspect
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from api.v1.api import api_router
from api.v1.endpoints import agent_controller
from dependencies import get_current_user_id_short_lived


def agent_route_pairs():
    return {
        (method, f"/api/v1{route.path}")
        for route in api_router.routes
        if route.path.startswith("/agent")
        for method in (route.methods or set())
    }


def test_agent_route_surface_is_complete():
    expected = {
        ("GET", "/api/v1/agent/capabilities"),
        ("POST", "/api/v1/agent/conversations"),
        ("GET", "/api/v1/agent/conversations"),
        ("GET", "/api/v1/agent/conversations/{conversation_id}"),
        ("PATCH", "/api/v1/agent/conversations/{conversation_id}"),
        ("POST", "/api/v1/agent/conversations/{conversation_id}/messages"),
        ("GET", "/api/v1/agent/runs/{run_id}"),
        ("GET", "/api/v1/agent/runs/{run_id}/events"),
        ("POST", "/api/v1/agent/runs/{run_id}/cancel"),
        ("GET", "/api/v1/agent/profile"),
        ("PATCH", "/api/v1/agent/profile"),
    }
    assert expected <= agent_route_pairs()


def test_agent_message_submission_requires_idempotency_header():
    parameter = inspect.signature(agent_controller.submit_message).parameters[
        "idempotency_key"
    ]
    assert parameter.default.alias == "Idempotency-Key"
    assert parameter.default.is_required()


def test_agent_sse_uses_short_lived_authentication_dependency():
    route = next(
        route
        for route in api_router.routes
        if route.path == "/agent/runs/{run_id}/events"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert get_current_user_id_short_lived in dependency_calls
