import pytest

@pytest.mark.asyncio
async def test_login_success(client):
    """
    Test: POST /api/auth/login
    Expected: 200 OK, Token returned
    """
    payload = {
        "username": "testuser",
        "password": "validpassword",
        "client_info": {} # optional
    }
    # Note: Dependencies like get_client_info usually extract from headers/request.
    # In auth.py: login(request: LoginRequest, db, client_info=Depends(get_client_info))
    # mocks in conftest.py ensure auth_service.login_with_password returns a token.
    
    resp = await client.post("/api/auth/login", json=payload)
    
    # If get_client_info dependency fails (e.g. strict check), we might need to mock it.
    # But usually it just parses headers.
    
    # If 422: LoginRequest validation error or missing fields.
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "access_token" in data["token"]
    assert data["token"]["access_token"] == "fake-token"

@pytest.mark.asyncio
async def test_login_validation_error(client):
    """
    Test: POST /api/auth/login with missing field
    Expected: 422 Unprocessable Entity
    """
    payload = {"username": "testuser"} # missing password
    resp = await client.post("/api/auth/login", json=payload)
    assert resp.status_code == 422
