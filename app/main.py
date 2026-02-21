from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from bson import ObjectId
from bson.errors import InvalidId
import logging

from app.config import settings
from app.database import connect_to_mongo, close_mongo_connection, get_database
from app.models import (
    FeedCreate, FeedUpdate, FeedResponse,
    PreferencesUpdate, PreferencesResponse,
    ArticleResponse, UserPreferences
)
from app.services.ai_processor import ai_processor
from app.services.scheduler import start_scheduler, shutdown_scheduler
from app.services.feeder import rss_feeder

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting News Diet application")
    
    # Connect to MongoDB
    await connect_to_mongo()
    
    # Ensure Ollama model is available
    logger.info("Checking Ollama model availability...")
    model_ready = await ai_processor.ensure_model_available()
    if not model_ready:
        logger.warning("Ollama model not ready. AI features may be limited.")
    
    # Initialize default feeds if none exist
    await initialize_default_feeds()
    
    # Initialize default preferences if none exist
    await initialize_default_preferences()
    
    # Migrate existing articles to add is_hidden field
    await migrate_articles_schema()
    
    # Start scheduler
    start_scheduler()
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("Shutting down News Diet application")
    shutdown_scheduler()
    await close_mongo_connection()


# Initialize FastAPI app
app = FastAPI(
    title="News Diet",
    description="AI-powered RSS news aggregator (Google Reader inspired)",
    version="1.0.0",
    lifespan=lifespan
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ============================================
# Initialization Functions
# ============================================

async def initialize_default_feeds():
    db = get_database()
    count = await db.feeds.count_documents({})
    
    if count == 0:
        logger.info("No feeds in database. Users can add feeds via the web UI at /feeds")


async def initialize_default_preferences():
    db = get_database()
    prefs = await db.preferences.find_one()
    
    if prefs is None:
        logger.info("Initializing default user preferences")
        
        default_prefs = {
            "interests": ["Python", "DevOps", "AI", "Web Development", "Open Source"],
            "exclude_topics": ["Cryptocurrency", "NFT"],
            "min_relevance_score": 5,
            "dark_mode": False,
            "updated_at": datetime.now(timezone.utc)
        }
        
        await db.preferences.insert_one(default_prefs)
        logger.info("Default preferences created")


async def migrate_articles_schema():
    """Backfill is_hidden field for articles created before this field was added."""
    db = get_database()
    
    # Update all articles without is_hidden field to set it to False
    result = await db.articles.update_many(
        {"is_hidden": {"$exists": False}},
        {"$set": {"is_hidden": False}}
    )
    
    if result.modified_count > 0:
        logger.info(f"Migrated {result.modified_count} existing articles to add is_hidden field")


# ============================================
# Frontend Routes (HTML)
# ============================================

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, show_all: bool = False, filter_unread: bool = False, filter_starred: bool = False):
    db = get_database()
    
    # Get user preferences for min_relevance_score
    prefs = await db.preferences.find_one()
    min_score = prefs.get("min_relevance_score", 5) if prefs else 5
    dark_mode = prefs.get("dark_mode", False) if prefs else False
    
    # Build query based on parameters
    if filter_starred:
        # Show only starred articles (regardless of score or read status)
        query = {"is_starred": True}
    elif filter_unread:
        # Show all unread articles (regardless of relevance score)
        query = {"is_read": False}
    elif show_all:
        # Show all articles including low relevance ones
        query = {}
    else:
        # Default view: only show unread articles meeting minimum relevance score
        query = {"relevance_score": {"$gte": min_score}, "is_read": False}
    
    # Get articles sorted by published date (newest first)
    cursor = db.articles.find(query).sort("published_at", -1).limit(100)
    articles = await cursor.to_list(length=100)
    
    # Convert ObjectId to string for template
    for article in articles:
        article["id"] = str(article["_id"])
    
    # Get unread count (only relevant articles)
    unread_count = await db.articles.count_documents({"is_read": False, "relevance_score": {"$gte": min_score}})
    
    # Get starred count
    starred_count = await db.articles.count_documents({"is_starred": True})
    
    # Get total articles count (fast estimated count for "All" view indicator)
    total_count = await db.articles.estimated_document_count()
    
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "articles": articles,
            "unread_count": unread_count,
            "starred_count": starred_count,
            "total_count": total_count,
            "min_relevance_score": min_score,
            "show_all": show_all,
            "filter_unread": filter_unread,
            "filter_starred": filter_starred,
            "dark_mode": dark_mode
        }
    )


@app.get("/feeds", response_class=HTMLResponse)
async def feeds_page(request: Request):
    db = get_database()
    
    cursor = db.feeds.find().sort("name", 1)
    feeds = await cursor.to_list(length=100)
    
    # Convert ObjectId to string
    for feed in feeds:
        feed["id"] = str(feed["_id"])
    
    # Get dark mode preference
    prefs = await db.preferences.find_one()
    dark_mode = prefs.get("dark_mode", False) if prefs else False
    
    return templates.TemplateResponse(
        "feeds.html",
        {
            "request": request,
            "feeds": feeds,
            "dark_mode": dark_mode
        }
    )


@app.get("/preferences", response_class=HTMLResponse)
async def preferences_page(request: Request):
    db = get_database()
    
    prefs = await db.preferences.find_one()
    
    if prefs:
        prefs["id"] = str(prefs["_id"])
        # Convert lists to comma-separated strings for form
        prefs["interests_str"] = ", ".join(prefs.get("interests", []))
        prefs["exclude_topics_str"] = ", ".join(prefs.get("exclude_topics", []))
        dark_mode = prefs.get("dark_mode", False)
    else:
        prefs = {
            "interests_str": "",
            "exclude_topics_str": "",
            "min_relevance_score": 5,
            "dark_mode": False,
            "prune_after_days": 30
        }
        dark_mode = False
    
    return templates.TemplateResponse(
        "preferences.html",
        {
            "request": request,
            "preferences": prefs,
            "dark_mode": dark_mode,
            "model_name": settings.ollama_model
        }
    )


# ============================================
# API Routes - Articles
# ============================================

@app.post("/api/articles/refresh")
async def refresh_articles():
    try:
        new_count = await rss_feeder.fetch_all_enabled_feeds()
        return {"success": True, "new_articles": new_count, "message": f"Fetched {new_count} new articles"}
    except Exception as e:
        logger.error(f"Error refreshing articles: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh articles. Please try again.")


@app.patch("/api/articles/{article_id}/read")
async def mark_article_read(article_id: str, is_read: bool = True):
    db = get_database()
    
    try:
        oid = ObjectId(article_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid article ID format")
    
    try:
        result = await db.articles.update_one(
            {"_id": oid},
            {"$set": {"is_read": is_read}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Article not found")
        
        return {"success": True, "is_read": is_read}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating article: {e}")
        raise HTTPException(status_code=500, detail="Failed to update article")


@app.patch("/api/articles/{article_id}/star")
async def toggle_article_star(article_id: str, is_starred: bool = True):
    db = get_database()
    
    try:
        oid = ObjectId(article_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid article ID format")
    
    try:
        result = await db.articles.update_one(
            {"_id": oid},
            {"$set": {"is_starred": is_starred}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Article not found")
        
        return {"success": True, "is_starred": is_starred}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating article star status: {e}")
        raise HTTPException(status_code=500, detail="Failed to update article")


# ============================================
# API Routes - Feeds
# ============================================

@app.get("/api/feeds", response_model=list[FeedResponse])
async def get_feeds():
    db = get_database()
    
    cursor = db.feeds.find().sort("name", 1)
    feeds = await cursor.to_list(length=100)
    
    # Convert to response model
    return [
        FeedResponse(
            id=str(feed["_id"]),
            url=feed["url"],
            name=feed["name"],
            enabled=feed["enabled"],
            last_fetched_at=feed.get("last_fetched_at"),
            error_count=feed.get("error_count", 0),
            created_at=feed["created_at"]
        )
        for feed in feeds
    ]


@app.post("/api/feeds", response_model=FeedResponse)
async def create_feed(feed: FeedCreate):
    db = get_database()
    
    # Convert HttpUrl to string for storage
    feed_url = str(feed.url)
    
    # Check if feed already exists
    existing = await db.feeds.find_one({"url": feed_url})
    if existing:
        raise HTTPException(status_code=400, detail="Feed already exists")
    
    feed_doc = {
        "url": feed_url,
        "name": feed.name.strip(),
        "enabled": feed.enabled,
        "error_count": 0,
        "created_at": datetime.now(timezone.utc)
    }
    
    result = await db.feeds.insert_one(feed_doc)
    feed_doc["_id"] = result.inserted_id
    
    return FeedResponse(
        id=str(feed_doc["_id"]),
        url=feed_doc["url"],
        name=feed_doc["name"],
        enabled=feed_doc["enabled"],
        last_fetched_at=None,
        error_count=0,
        created_at=feed_doc["created_at"]
    )


@app.patch("/api/feeds/{feed_id}")
async def update_feed(feed_id: str, feed_update: FeedUpdate):
    db = get_database()
    
    try:
        oid = ObjectId(feed_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")
    
    update_data = {k: v for k, v in feed_update.model_dump(exclude_unset=True).items()}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    
    result = await db.feeds.update_one(
        {"_id": oid},
        {"$set": update_data}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    return {"success": True}


@app.delete("/api/feeds/{feed_id}")
async def delete_feed(feed_id: str):
    db = get_database()
    
    try:
        oid = ObjectId(feed_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid feed ID format")
    
    # First, get the feed to retrieve its name (needed for article deletion)
    feed = await db.feeds.find_one({"_id": oid})
    
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    # Delete the feed
    result = await db.feeds.delete_one({"_id": oid})
    
    # Delete associated articles if configured to do so
    deleted_articles_count = 0
    if settings.delete_articles_on_feed_removal:
        feed_name = feed.get("name", "")
        if feed_name:
            articles_result = await db.articles.delete_many({"source": feed_name})
            deleted_articles_count = articles_result.deleted_count
            logger.info(f"Deleted {deleted_articles_count} articles from feed '{feed_name}'")
    
    return {
        "success": True,
        "deleted_articles": deleted_articles_count
    }


# ============================================
# API Routes - Preferences
# ============================================

@app.get("/api/preferences", response_model=PreferencesResponse)
async def get_preferences():
    db = get_database()
    
    prefs = await db.preferences.find_one()
    
    if prefs is None:
        # Return defaults
        return PreferencesResponse(
            interests=["Python", "DevOps", "AI", "Web Development"],
            exclude_topics=["Cryptocurrency"],
            min_relevance_score=5,
            dark_mode=False,
            prune_after_days=30,
            updated_at=datetime.now(timezone.utc)
        )
    
    return PreferencesResponse(
        interests=prefs.get("interests", []),
        exclude_topics=prefs.get("exclude_topics", []),
        min_relevance_score=prefs.get("min_relevance_score", 5),
        dark_mode=prefs.get("dark_mode", False),
        prune_after_days=prefs.get("prune_after_days", 30),
        updated_at=prefs.get("updated_at", datetime.now(timezone.utc))
    )


@app.put("/api/preferences")
async def update_preferences(prefs_update: PreferencesUpdate):
    db = get_database()
    
    update_data = {k: v for k, v in prefs_update.model_dump(exclude_unset=True).items()}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    # Upsert (update or insert)
    await db.preferences.update_one(
        {},
        {"$set": update_data},
        upsert=True
    )
    
    return {"success": True}


@app.delete("/api/articles")
async def delete_all_articles():
    db = get_database()
    
    try:
        result = await db.articles.delete_many({})
        logger.info(f"Deleted all articles. Count: {result.deleted_count}")
        return {
            "success": True,
            "deleted_count": result.deleted_count,
            "message": f"Deleted {result.deleted_count} articles"
        }
    except Exception as e:
        logger.error(f"Error deleting all articles: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete articles")


@app.post("/api/articles/recalculate")
async def recalculate_all_scores():
    db = get_database()
    
    try:
        # Get user preferences
        prefs_doc = await db.preferences.find_one()
        if prefs_doc is None:
            raise HTTPException(status_code=400, detail="User preferences not found. Please configure your preferences first.")
        
        preferences = UserPreferences(
            interests=prefs_doc.get("interests", []),
            exclude_topics=prefs_doc.get("exclude_topics", []),
            min_relevance_score=prefs_doc.get("min_relevance_score", 5),
            dark_mode=prefs_doc.get("dark_mode", False)
        )
        
        # Get all articles using a cursor to avoid loading all into memory
        cursor = db.articles.find({})
        
        # Process articles one by one with proper error handling
        from app.services.ai_processor import ai_processor
        
        processed = 0
        async for article in cursor:
            try:
                # Use the process_article method which handles both summary and scoring
                result = await ai_processor.process_article(
                    article.get("title", ""),
                    article.get("content", ""),
                    preferences
                )
                
                # Determine if article should be hidden based on new relevance score
                is_hidden = result["relevance_score"] < preferences.min_relevance_score if result["relevance_score"] is not None else False
                
                # Update article with new data
                await db.articles.update_one(
                    {"_id": article["_id"]},
                    {"$set": {
                        "summary": result["summary"],
                        "tags": result["tags"],
                        "relevance_score": result["relevance_score"],
                        "is_hidden": is_hidden
                    }}
                )
                processed += 1
                
            except Exception as e:
                logger.error(f"Error processing article {article.get('_id')}: {e}")
                continue
        
        logger.info(f"Recalculated scores for {processed} articles")
        return {
            "success": True,
            "processed_count": processed,
            "message": f"Recalculated scores for {processed} articles"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error recalculating scores: {e}")
        raise HTTPException(status_code=500, detail="Failed to recalculate scores")


# ============================================
# Health Check
# ============================================

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_reload
    )
