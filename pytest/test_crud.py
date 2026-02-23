import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from crud.user import user
from crud.job import job
from jobCollectionWebApi.schemas.user import UserCreate
from jobCollectionWebApi.schemas.job import JobCreate
from common.databases.models.user import User
from common.databases.models.job import Job

@pytest.fixture
def mock_session():
    """Mock database session for CRUD operations"""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    # For execute/scalars stuff
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session

@pytest.mark.asyncio
async def test_create_user(mock_session):
    """Test creating a new user"""
    user_in = UserCreate(
        username="newuser",
        email="new@example.com",
        password="secretpassword",
        nickname="New User"
    )
    
    # Mock behavior
    mock_session.flush.return_value = None
    mock_session.refresh.return_value = None
    
    # Call CRUD
    new_user = await user.create(mock_session, obj_in=user_in)
    
    # Assertions
    assert isinstance(new_user, User)
    assert new_user.username == "newuser"
    assert new_user.email == "new@example.com"
    # Verify DB interactions
    mock_session.add.assert_called_once()
    mock_session.flush.assert_called_once()
    mock_session.refresh.assert_called_once_with(new_user)
    # Password should be hashed
    assert new_user.hashed_password != "secretpassword"

@pytest.mark.asyncio
async def test_get_user_by_username(mock_session):
    """Test retrieving a user by username"""
    mock_user = User(id=1, username="founduser", email="found@example.com")
    
    # Mock execute result
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_user
    mock_session.execute.return_value = result_mock
    
    found = await user.get_by_username(mock_session, "founduser")
    
    assert found is not None
    assert found.id == 1
    assert found.username == "founduser"
    # Verify query structure roughly (optional/hard with SQLAlchemy mocks)
    mock_session.execute.assert_called_once()

@pytest.mark.asyncio
async def test_create_job(mock_session, monkeypatch):
    """Test creating a job and ensuring ES sync is handled"""
    # Mock search_service to prevent actual ES calls or sync internal errors
    from services.search_service import search_service
    mock_search = AsyncMock()
    monkeypatch.setattr(search_service, "upsert_job", mock_search)
    
    # Mock internal _sync_to_es to avoid complex query mocking if desired,
    # OR mock the session execute to return the job for _sync_to_es.
    # Let's mock _sync_to_es for simplicity as it involves complex joins.
    mock_sync = AsyncMock()
    monkeypatch.setattr(job, "_sync_to_es", mock_sync)
    
    job_in = JobCreate(
        title="Python Developer",
        description="Write code",
        salary_min=10000,
        salary_max=20000,
        location="Shanghai",
        company_id=1
    )
    
    new_job = await job.create(mock_session, obj_in=job_in)
    
    assert isinstance(new_job, Job)
    assert new_job.title == "Python Developer"
    
    # Verify commit was called (as per CRUDJob.create implementation)
    mock_session.commit.assert_called_once()
    # Verify sync was triggered
    mock_sync.assert_called_once()

