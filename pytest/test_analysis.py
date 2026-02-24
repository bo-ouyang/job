import pytest
import datetime

@pytest.mark.asyncio
async def test_get_major_presets(client):
    """
    Test: GET /api/analysis/major/presets
    Expected: 200 OK, List of majors, correct mock data
    """
    resp = await client.get("/api/analysis/major/presets")
    assert resp.status_code == 200
    data = resp.json()
    
    assert isinstance(data, list)
    assert len(data) == 1
    item = data[0]
    assert item["major_name"] == "Computer Science"
    assert item["category"] == "IT"
    assert "keywords" in item

@pytest.mark.asyncio
async def test_ai_advice_success(client):
    """
    Test: POST /api/analysis/ai/advice
    Expected: 200 OK, Mocked AI response
    """
    payload = {
        "major_name": "Information Security",
        "skills": ["Network Security", "Python"]
    }
    resp = await client.post("/api/analysis/ai/advice", json=payload)
    
    assert resp.status_code == 200
    # The return value from mock_ai_service in conftest.py
    assert resp.json() == "Mocked AI Advice Response"

@pytest.mark.asyncio
async def test_ai_advice_empty_skills(client):
    """
    Test: POST /api/analysis/ai/advice with empty skills
    Expected: 200 OK (AI Service handles it, usually with fallback) 
    or 422 if we enforce validation.
    Implementation used List[str], so empty list [] is valid JSON.
    """
    payload = {
        "major_name": "Unknown Major",
        "skills": []
    }
    resp = await client.post("/api/analysis/ai/advice", json=payload)
    assert resp.status_code == 200
    assert resp.json() == "Mocked AI Advice Response"

@pytest.mark.asyncio
async def test_ai_advice_invalid_payload(client):
    """
    Test: POST /api/analysis/ai/advice with missing fields
    Expected: 422 Validation Error (FastAPI default)
    """
    payload = {"major_name": "Just Name Request"}
    resp = await client.post("/api/analysis/ai/advice", json=payload)
    assert resp.status_code == 422
