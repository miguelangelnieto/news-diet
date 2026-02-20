import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta, timezone
from app.config import settings
from app.services.feeder import rss_feeder
from app.database import get_database

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def scheduled_feed_fetch():
    logger.info("Starting scheduled RSS feed fetch")
    try:
        new_count = await rss_feeder.fetch_all_enabled_feeds()
        logger.info(f"Scheduled fetch completed. {new_count} new articles added.")
    except Exception as e:
        logger.error(f"Error in scheduled feed fetch: {e}")


async def cleanup_old_articles():
    """Delete old unstarred articles based on user's prune_after_days preference."""
    logger.info("Starting cleanup of old articles")
    try:
        db = get_database()
        
        # Get prune_after_days from preferences
        prefs = await db.preferences.find_one()
        prune_after_days = prefs.get("prune_after_days", 30) if prefs else 30
        
        # Delete articles older than prune_after_days that are NOT starred
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=prune_after_days)
        result = await db.articles.delete_many({
            "is_starred": {"$ne": True},  # Not starred
            "created_at": {"$lt": cutoff_date}  # Older than cutoff
        })
        deleted_count = result.deleted_count
        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old articles (older than {prune_after_days} days, kept starred articles)")
        else:
            logger.debug("No old articles to delete")
    except Exception as e:
        logger.error(f"Error in cleanup job: {e}")


def start_scheduler():
    try:
        # Schedule RSS fetch job
        scheduler.add_job(
            scheduled_feed_fetch,
            trigger=IntervalTrigger(hours=settings.rss_fetch_interval_hours),
            id="rss_fetch_job",
            name="Fetch RSS feeds",
            replace_existing=True
        )
        
        # Schedule cleanup job (runs daily)
        scheduler.add_job(
            cleanup_old_articles,
            trigger=IntervalTrigger(hours=24),
            id="cleanup_old_articles_job",
            name="Cleanup old articles (keep starred)",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info(f"Scheduler started. RSS feeds will be fetched every {settings.rss_fetch_interval_hours} hour(s)")
        logger.info("Cleanup job scheduled to run every 24 hours (keeps starred articles)")
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")


def shutdown_scheduler():
    try:
        if scheduler.running:
            scheduler.shutdown()
            logger.info("Scheduler shut down")
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {e}")
