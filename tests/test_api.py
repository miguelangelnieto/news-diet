"""Tests for API endpoints."""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime
from bson import ObjectId


# Mock MongoDB before importing app
@pytest.fixture(autouse=True)
def mock_mongodb():
    with patch('app.database.motor_client') as mock_client:
        mock_db = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        yield mock_db


@pytest.fixture
def mock_db():
    db = MagicMock()
    
    # Mock collections
    db.articles = MagicMock()
    db.feeds = MagicMock()
    db.preferences = MagicMock()
    
    return db


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_check(self, mock_mongodb):
        """Test that health endpoint returns healthy status."""
        with patch('app.database.get_database') as mock_get_db:
            mock_get_db.return_value = mock_mongodb
            
            # Import app after mocking
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/health")
                
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert "timestamp" in data


class TestPreferencesAPI:
    @pytest.mark.asyncio
    async def test_get_preferences_default(self, mock_mongodb):
        """Test getting preferences when none exist."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.preferences.find_one = AsyncMock(return_value=None)
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/preferences")
                
                assert response.status_code == 200
                data = response.json()
                assert "interests" in data
                assert "dark_mode" in data
                assert "prune_after_days" in data
                assert data["prune_after_days"] == 30  # Default value
    
    @pytest.mark.asyncio
    async def test_update_preferences(self, mock_mongodb):
        """Test updating preferences."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.preferences.update_one = AsyncMock()
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.put(
                    "/api/preferences",
                    json={"dark_mode": True}
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_update_preferences_with_prune_days(self, mock_mongodb):
        """Test updating preferences with prune_after_days."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.preferences.update_one = AsyncMock()
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.put(
                    "/api/preferences",
                    json={"prune_after_days": 60}
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
    
    @pytest.mark.asyncio
    async def test_get_preferences_with_custom_prune_days(self, mock_mongodb):
        """Test getting preferences with custom prune_after_days."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.preferences.find_one = AsyncMock(return_value={
                "interests": ["Python"],
                "exclude_topics": ["Crypto"],
                "min_relevance_score": 7,
                "dark_mode": True,
                "prune_after_days": 90,
                "updated_at": datetime.now()
            })
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/preferences")
                
                assert response.status_code == 200
                data = response.json()
                assert data["prune_after_days"] == 90


class TestArticlesAPI:
    @pytest.mark.asyncio
    async def test_mark_article_read_invalid_id(self, mock_mongodb):
        """Test marking article read with invalid ID format."""
        with patch('app.database.get_database') as mock_get_db:
            mock_get_db.return_value = mock_mongodb
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.patch(
                    "/api/articles/invalid-id/read?is_read=true"
                )
                
                assert response.status_code == 400
                data = response.json()
                assert "Invalid article ID" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_mark_article_read_valid_id(self, mock_mongodb):
        """Test marking article read with valid ID."""
        valid_oid = str(ObjectId())
        
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_result = MagicMock()
            mock_result.matched_count = 1
            mock_db.articles.update_one = AsyncMock(return_value=mock_result)
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.patch(
                    f"/api/articles/{valid_oid}/read?is_read=true"
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["is_read"] is True


class TestFeedsAPI:
    @pytest.mark.asyncio
    async def test_create_feed(self, mock_mongodb):
        """Test creating a new feed."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.feeds.find_one = AsyncMock(return_value=None)  # No existing feed
            mock_result = MagicMock()
            mock_result.inserted_id = ObjectId()
            mock_db.feeds.insert_one = AsyncMock(return_value=mock_result)
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/feeds",
                    json={
                        "url": "https://example.com/rss",
                        "name": "Test Feed"
                    }
                )
                
                assert response.status_code == 200
                data = response.json()
                assert data["name"] == "Test Feed"
                assert data["enabled"] is True
    
    @pytest.mark.asyncio
    async def test_create_duplicate_feed(self, mock_mongodb):
        """Test creating a feed that already exists."""
        with patch('app.database.get_database') as mock_get_db:
            mock_db = MagicMock()
            mock_db.feeds.find_one = AsyncMock(return_value={"url": "https://example.com/rss"})
            mock_get_db.return_value = mock_db
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post(
                    "/api/feeds",
                    json={
                        "url": "https://example.com/rss",
                        "name": "Test Feed"
                    }
                )
                
                assert response.status_code == 400
                data = response.json()
                assert "already exists" in data["detail"]
    
    @pytest.mark.asyncio
    async def test_delete_feed_invalid_id(self, mock_mongodb):
        """Test deleting feed with invalid ID format."""
        with patch('app.database.get_database') as mock_get_db:
            mock_get_db.return_value = mock_mongodb
            
            from app.main import app
            
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.delete("/api/feeds/invalid-id")
                
                assert response.status_code == 400
                data = response.json()
                assert "Invalid feed ID" in data["detail"]
