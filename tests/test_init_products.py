import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "jobCollectionWebApi" / "init_products.py"
PROJECT_ROOT = Path(__file__).parents[1]


def _load_init_products():
    spec = importlib.util.spec_from_file_location("init_products", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_init_products_manages_database_lifecycle(monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT_ROOT))
    init_products = _load_init_products()
    events = []
    session = object()

    class SessionContext:
        async def __aenter__(self):
            events.append("session_open")
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            events.append("session_close")

    class DatabaseManager:
        async_session = SessionContext

        async def initialize(self):
            events.append("initialize")

        async def close(self):
            events.append("database_close")

    class PricingService:
        async def ensure_pricing_products(self, received_session):
            assert received_session is session
            events.append("ensure_products")
            return 0

    monkeypatch.setattr(init_products, "db_manager", DatabaseManager())
    monkeypatch.setattr(init_products, "ai_access_service", PricingService())

    await init_products.init()

    assert events == [
        "initialize",
        "session_open",
        "ensure_products",
        "session_close",
        "database_close",
    ]
