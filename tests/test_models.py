"""Tests for Pydantic models."""
import pytest
from datetime import datetime
from bson import ObjectId
from app.models import (
    Article, ArticleCreate, ArticleResponse,
    Feed, FeedCreate, FeedUpdate, FeedResponse,
    UserPreferences, PreferencesUpdate, PreferencesResponse
)


class TestArticleModels:
    def test_article_create_minimal(self):
        """Test creating ArticleCreate with minimal fields."""
        article = ArticleCreate(
            url="https://example.com/article",
            title="Test Article",
            source="Test Source",
            published_at=datetime.utcnow()
        )
        assert article.url == "https://example.com/article"
        assert article.title == "Test Article"
        assert article.tags == []
        assert article.relevance_score is None
    
    def test_article_create_full(self):
        """Test creating ArticleCreate with all fields."""
        now = datetime.utcnow()
        article = ArticleCreate(
            url="https://example.com/article",
            title="Test Article",
            source="Test Source",
            published_at=now,
            summary="This is a summary",
            relevance_score=8,
            tags=["python", "testing"]
        )
        assert article.summary == "This is a summary"
        assert article.relevance_score == 8
        assert article.tags == ["python", "testing"]
    
    def test_article_response(self):
        """Test ArticleResponse model."""
        now = datetime.utcnow()
        response = ArticleResponse(
            id="507f1f77bcf86cd799439011",
            url="https://example.com",
            title="Test",
            source="Source",
            published_at=now,
            tags=[],
            is_read=False,
            created_at=now
        )
        assert response.id == "507f1f77bcf86cd799439011"
        assert response.is_read is False


class TestFeedModels:
    def test_feed_create_minimal(self):
        """Test creating FeedCreate with minimal fields."""
        feed = FeedCreate(
            url="https://example.com/rss",
            name="Test Feed"
        )
        assert feed.url == "https://example.com/rss"
        assert feed.name == "Test Feed"
        assert feed.enabled is True  # Default
    
    def test_feed_create_disabled(self):
        """Test creating FeedCreate with enabled=False."""
        feed = FeedCreate(
            url="https://example.com/rss",
            name="Test Feed",
            enabled=False
        )
        assert feed.enabled is False
    
    def test_feed_update_partial(self):
        """Test FeedUpdate with partial data."""
        update = FeedUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.enabled is None
    
    def test_feed_response(self):
        """Test FeedResponse model."""
        now = datetime.utcnow()
        response = FeedResponse(
            id="507f1f77bcf86cd799439011",
            url="https://example.com/rss",
            name="Test Feed",
            enabled=True,
            last_fetched_at=now,
            error_count=0,
            created_at=now
        )
        assert response.error_count == 0


class TestPreferencesModels:
    def test_preferences_defaults(self):
        """Test UserPreferences with defaults."""
        prefs = UserPreferences()
        assert prefs.interests == []
        assert prefs.exclude_topics == []
        assert prefs.min_relevance_score == 5
        assert prefs.dark_mode is False
        assert prefs.prune_after_days == 30
    
    def test_preferences_update_partial(self):
        """Test PreferencesUpdate with partial data."""
        update = PreferencesUpdate(dark_mode=True)
        assert update.dark_mode is True
        assert update.interests is None
    
    def test_preferences_update_score_validation(self):
        """Test that min_relevance_score is validated."""
        # Valid score
        update = PreferencesUpdate(min_relevance_score=7)
        assert update.min_relevance_score == 7
        
        # Invalid score should raise error
        with pytest.raises(ValueError):
            PreferencesUpdate(min_relevance_score=15)
        
        with pytest.raises(ValueError):
            PreferencesUpdate(min_relevance_score=-1)
    
    def test_preferences_prune_days_validation(self):
        """Test that prune_after_days is validated."""
        # Valid values
        update = PreferencesUpdate(prune_after_days=60)
        assert update.prune_after_days == 60
        
        update = PreferencesUpdate(prune_after_days=1)
        assert update.prune_after_days == 1
        
        update = PreferencesUpdate(prune_after_days=365)
        assert update.prune_after_days == 365
        
        # Invalid values should raise error
        with pytest.raises(ValueError):
            PreferencesUpdate(prune_after_days=0)
        
        with pytest.raises(ValueError):
            PreferencesUpdate(prune_after_days=400)
        
        with pytest.raises(ValueError):
            PreferencesUpdate(prune_after_days=-1)
    
    def test_preferences_response(self):
        """Test PreferencesResponse model."""
        now = datetime.utcnow()
        response = PreferencesResponse(
            interests=["Python", "AI"],
            exclude_topics=["Crypto"],
            min_relevance_score=6,
            dark_mode=True,
            prune_after_days=30,
            updated_at=now
        )
        assert response.interests == ["Python", "AI"]
        assert response.dark_mode is True
        assert response.prune_after_days == 30


class TestObjectIdValidation:
    def test_valid_object_id_string(self):
        """Test that valid ObjectId strings are accepted."""
        oid = ObjectId()
        article = Article(
            id=str(oid),
            url="https://example.com",
            title="Test",
            source="Source",
            published_at=datetime.utcnow()
        )
        # The validator should convert string to ObjectId
        assert article.id is not None
    
    def test_valid_object_id_object(self):
        """Test that ObjectId objects are accepted."""
        oid = ObjectId()
        article = Article(
            id=oid,
            url="https://example.com",
            title="Test",
            source="Source",
            published_at=datetime.utcnow()
        )
        assert article.id == oid
    
    def test_invalid_object_id(self):
        """Test that invalid ObjectId strings are rejected."""
        with pytest.raises(ValueError):
            Article(
                id="invalid-oid",
                url="https://example.com",
                title="Test",
                source="Source",
                published_at=datetime.utcnow()
            )
