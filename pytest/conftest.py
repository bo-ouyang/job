import sys
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

# 1. Setup Path to include jobCollectionWebApi
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../jobCollectionWebApi')))

from main import app
from dependencies import get_db
from common.databases.RedisManager import redis_manager
from common.databases.MysqlManager import db_manager
from services.ai_service import ai_service

# 2. Mock Global Services (DB, Redis, AI) to prevent independent service usage
@pytest.fixture(autouse=True)
def mock_db_lifecycle(monkeypatch):
    """Mock Database Manager lifecycle methods to prevent real connection"""
    monkeypatch.setattr(db_manager, "initialize", AsyncMock())
    monkeypatch.setattr(db_manager, "close", AsyncMock())
    monkeypatch.setattr(db_manager, "health_check", AsyncMock(return_value=True))

    # Mock get_session for Middleware/Dependencies that use it directly
    # Assuming usage: async with await db_manager.get_session() as session:
    session_mock = AsyncMock()
    session_mock.__aenter__.return_value = session_mock
    session_mock.__aexit__.return_value = None
    
    # get_session is likely async, returning the session object
    monkeypatch.setattr(db_manager, "get_session", AsyncMock(return_value=session_mock))

@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    """Mock Redis Manager"""
    mock = AsyncMock()
    mock.get_cache.return_value = None  # Force cache miss by default
    monkeypatch.setattr(redis_manager, "get_cache", mock.get_cache)
    monkeypatch.setattr(redis_manager, "set_cache", mock.set_cache)
    return mock

@pytest.fixture(autouse=True)
def mock_ai_service(monkeypatch):
    """Mock AI Service"""
    mock = AsyncMock()
    mock.generate_career_advice.return_value = "Mocked AI Advice Response"
    monkeypatch.setattr(ai_service, "generate_career_advice", mock.generate_career_advice)
    return mock


# Mock Search Service
from services.search_service import search_service
@pytest.fixture(autouse=True)
def mock_search_service(monkeypatch):
    mock = AsyncMock()
    # Return (items, total)
    mock.search_jobs.return_value = ([], 0)
    monkeypatch.setattr(search_service, "search_jobs", mock.search_jobs)
    return mock

# Mock Auth Service
from services.auth_service import auth_service
@pytest.fixture(autouse=True)
def mock_auth_service(monkeypatch):
    mock = AsyncMock()
    # Mock login response matching LoginResponse schema
    mock_response = {
        "token": {
            "access_token": "fake-token",
            "token_type": "bearer",
            "expires_in": 3600
        },
        "user": {"id": 1, "username": "testuser", "role": "user"},
        "is_new_user": False
    }
    mock.login_with_password.return_value = mock_response
    monkeypatch.setattr(auth_service, "login_with_password", mock.login_with_password)
    return mock

# Mock CRUD Job Search
from crud import job as crud_job
@pytest.fixture(autouse=True)
def mock_crud_job_search(monkeypatch):
    mock = AsyncMock()
    mock.search.return_value = ([], 0)
    # Also mock get_by_source_url for create_job if needed
    monkeypatch.setattr(crud_job, "search", mock.search)
    return mock

# 3. Test Client Fixture
@pytest_asyncio.fixture
async def client():
    """Async HTTP Client for testing FastAPI app"""
    # Override DB dependency
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    
    # Use ASGITransport for connecting to FastAPI app directly
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()
