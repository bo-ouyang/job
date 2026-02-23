import pytest
from dependencies import get_current_user
from main import app

# Fixture to simulate logged-in user
@pytest.fixture
def override_auth():
    async def mock_get_current_user():
        from types import SimpleNamespace
        return SimpleNamespace(id=1, username="test_user", role="user")
    
    app.dependency_overrides[get_current_user] = mock_get_current_user
    yield
    # Clean up
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

@pytest.mark.asyncio
async def test_public_jobs(client):
    """
    Test: GET /api/jobs/public/jobs
    Expected: 200 OK
    """
    # Note: SearchService is mocked to return ([], 0)
    resp = await client.get("/api/jobs/public/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []

@pytest.mark.asyncio
async def test_search_jobs_authenticated(client, override_auth):
    """
    Test: GET /api/jobs/jobs (Authenticated)
    Expected: 200 OK
    """
    resp = await client.get("/api/jobs/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
