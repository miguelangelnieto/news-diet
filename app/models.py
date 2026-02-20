from pydantic import BaseModel, Field, ConfigDict
from pydantic.networks import HttpUrl
from datetime import datetime, timezone
from bson import ObjectId
from pydantic.functional_validators import BeforeValidator
from typing import Annotated


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def validate_object_id(v: str | ObjectId) -> ObjectId:
    if isinstance(v, ObjectId):
        return v
    if ObjectId.is_valid(v):
        return ObjectId(v)
    raise ValueError("Invalid ObjectId")


PyObjectId = Annotated[ObjectId, BeforeValidator(validate_object_id)]


# ============================================
# Article Models
# ============================================

class Article(BaseModel):
    id: PyObjectId | None = Field(default=None, alias="_id")
    url: str
    title: str
    source: str
    published_at: datetime
    summary: str | None = None
    relevance_score: int | None = None
    tags: list[str] = Field(default_factory=list)
    is_read: bool = False
    is_starred: bool = False
    is_hidden: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str}
    )


class ArticleCreate(BaseModel):
    url: str
    title: str
    source: str
    published_at: datetime
    summary: str | None = None
    relevance_score: int | None = None
    tags: list[str] = Field(default_factory=list)


class ArticleResponse(BaseModel):
    id: str
    url: str
    title: str
    source: str
    published_at: datetime
    summary: str | None = None
    relevance_score: int | None = None
    tags: list[str]
    is_read: bool
    is_starred: bool
    is_hidden: bool
    created_at: datetime


# ============================================
# Feed Models
# ============================================

class Feed(BaseModel):
    id: PyObjectId | None = Field(default=None, alias="_id")
    url: str
    name: str
    enabled: bool = True
    last_fetched_at: datetime | None = None
    error_count: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str}
    )


class FeedCreate(BaseModel):
    url: HttpUrl
    name: str
    enabled: bool = True


class FeedUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None


class FeedResponse(BaseModel):
    id: str
    url: str
    name: str
    enabled: bool
    last_fetched_at: datetime | None
    error_count: int
    created_at: datetime


# ============================================
# User Preferences Models
# ============================================

class UserPreferences(BaseModel):
    id: PyObjectId | None = Field(default=None, alias="_id")
    interests: list[str] = Field(default_factory=list)
    exclude_topics: list[str] = Field(default_factory=list)
    min_relevance_score: int = Field(default=5, ge=0, le=10)
    dark_mode: bool = False
    prune_after_days: int = Field(default=30, ge=1, le=365)
    updated_at: datetime = Field(default_factory=utc_now)
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str}
    )


class PreferencesUpdate(BaseModel):
    interests: list[str] | None = None
    exclude_topics: list[str] | None = None
    min_relevance_score: int | None = Field(None, ge=0, le=10)
    dark_mode: bool | None = None
    prune_after_days: int | None = Field(None, ge=1, le=365)


class PreferencesResponse(BaseModel):
    interests: list[str]
    exclude_topics: list[str]
    min_relevance_score: int
    dark_mode: bool
    prune_after_days: int
    updated_at: datetime
