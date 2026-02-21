from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Global database client and database instances
client: AsyncIOMotorClient | None = None
db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo() -> None:
    global client, db
    
    try:
        client = AsyncIOMotorClient(settings.mongodb_url)
        db = client[settings.mongodb_db]
        
        # Test connection
        await client.admin.command('ping')
        logger.info(f"Connected to MongoDB at {settings.mongodb_url}")
        
        # Create indexes
        await create_indexes()
        
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise


async def close_mongo_connection() -> None:
    global client
    
    if client:
        client.close()
        logger.info("Closed MongoDB connection")


async def create_indexes() -> None:
    if db is None:
        return
    
    # Articles collection indexes
    # CRITICAL: Unique index on URL prevents duplicate articles across all feeds
    await db.articles.create_index("url", unique=True)
    
    # Combined indexes for dashboard filtering and sorting
    # Default view: filter by unread + relevance score, sort by date
    await db.articles.create_index([("is_read", 1), ("published_at", -1), ("relevance_score", -1)])
    
    # Count unread articles: filter by unread + relevance score (no sort)
    await db.articles.create_index([("is_read", 1), ("relevance_score", -1)])
    
    # Starred view: filter by starred, sort by date
    await db.articles.create_index([("is_starred", 1), ("published_at", -1)])
    
    # Sorting by date only (All view)
    await db.articles.create_index([("published_at", -1)])
    
    # For cleanup task: old unstarred articles (match cleanup_old_articles filter on created_at)
    await db.articles.create_index([("is_starred", 1), ("created_at", 1)])
    
    # Other useful indexes
    await db.articles.create_index("source")
    await db.articles.create_index([("is_hidden", 1), ("published_at", -1)])
    
    # Feeds collection indexes
    await db.feeds.create_index("url", unique=True)
    await db.feeds.create_index("enabled")
    await db.feeds.create_index("name")
    
    logger.info("Database indexes created successfully")


def get_database() -> AsyncIOMotorDatabase:
    if db is None:
        raise RuntimeError("Database not initialized. Call connect_to_mongo() first.")
    return db
