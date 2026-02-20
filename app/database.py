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
    # This is the second layer of deduplication (see feeder.py for full strategy)
    await db.articles.create_index("url", unique=True)
    await db.articles.create_index([("published_at", -1)])
    await db.articles.create_index([("is_read", 1), ("published_at", -1)])
    await db.articles.create_index([("relevance_score", -1)])
    await db.articles.create_index([("is_starred", 1), ("published_at", -1)])
    await db.articles.create_index([("is_hidden", 1), ("published_at", -1)])
    await db.articles.create_index("source")
    
    # Feeds collection indexes
    await db.feeds.create_index("url", unique=True)
    await db.feeds.create_index("enabled")
    
    logger.info("Database indexes created successfully")


def get_database() -> AsyncIOMotorDatabase:
    if db is None:
        raise RuntimeError("Database not initialized. Call connect_to_mongo() first.")
    return db
