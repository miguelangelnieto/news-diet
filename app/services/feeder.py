import feedparser
import logging
import httpx
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from pymongo.errors import DuplicateKeyError
from app.database import get_database
from app.models import UserPreferences
from app.services.ai_processor import ai_processor
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

# Constants
FEED_FETCH_TIMEOUT = 30  # seconds


class RSSFeeder:
    def __init__(self):
        self.db = None
    
    def _ensure_db(self):
        if self.db is None:
            self.db = get_database()
    
    @staticmethod
    def _clean_html(html_content: str) -> str:
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, 'html.parser')
        return soup.get_text(separator=' ', strip=True)
    
    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            return date_parser.parse(date_str)
        except (ValueError, TypeError):
            return None
    
    async def _fetch_feed_content(self, feed_url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=FEED_FETCH_TIMEOUT) as client:
                response = await client.get(feed_url, follow_redirects=True)
                response.raise_for_status()
                return response.text
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching feed: {feed_url}")
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP error fetching feed {feed_url}: {e.response.status_code}")
            return None
        except httpx.RequestError as e:
            logger.warning(f"Request error fetching feed {feed_url}: {e}")
            return None
    
    async def fetch_feed(self, feed_url: str, feed_name: str) -> int:
        """
        Fetch and process a single RSS feed.
        
        **Deduplication Strategy**: Articles are uniquely identified by their URL.
        Three layers prevent re-processing and re-summarizing:
        1. Application check: Query database before AI processing
        2. Database constraint: Unique index on 'url' field (database.py)
        3. Race condition handler: Catch DuplicateKeyError
        
        Args:
            feed_url: The RSS feed URL
            feed_name: Human-readable feed name
            
        Returns:
            Number of new articles added
        """
        self._ensure_db()
        
        try:
            logger.info(f"Fetching feed: {feed_name} ({feed_url})")
            
            # Fetch feed content with timeout
            feed_content = await self._fetch_feed_content(feed_url)
            if feed_content is None:
                return 0
            
            # Parse RSS feed
            feed = feedparser.parse(feed_content)
            
            if feed.bozo:
                logger.warning(f"Feed parse warning for {feed_name}: {feed.bozo_exception}")
            
            # Get user preferences for AI processing
            preferences = await self._get_user_preferences()
            
            new_articles_count = 0
            
            for entry in feed.entries:
                try:
                    # Extract article data
                    url = entry.get('link', '')
                    title = entry.get('title', 'No Title')
                    
                    # Check if article already exists (prevents re-processing and re-summarizing)
                    # This is the first layer of deduplication - query before processing
                    existing = await self.db.articles.find_one({"url": url})
                    if existing:
                        logger.debug(f"Skipping existing article: {title} ({url})")
                        continue
                    
                    # Get content/description
                    content = entry.get('summary', '') or entry.get('description', '')
                    content = self._clean_html(content)
                    
                    # Parse published date
                    published_str = entry.get('published', '') or entry.get('updated', '')
                    published_at = self._parse_date(published_str) or datetime.now(timezone.utc)
                    
                    # Process with AI
                    ai_result = await ai_processor.process_article(
                        title=title,
                        content=content,
                        preferences=preferences
                    )
                    
                    # Determine if article should be hidden based on relevance score threshold
                    min_score = preferences.min_relevance_score
                    is_hidden = ai_result["relevance_score"] < min_score if ai_result["relevance_score"] is not None else False
                    
                    # Create article document
                    article_doc = {
                        "url": url,
                        "title": title,
                        "source": feed_name,
                        "published_at": published_at,
                        "summary": ai_result["summary"],
                        "relevance_score": ai_result["relevance_score"],
                        "tags": ai_result["tags"],
                        "is_read": False,
                        "is_hidden": is_hidden,
                        "created_at": datetime.now(timezone.utc)
                    }
                    
                    # Insert into database (handle race condition)
                    # This is the third layer of deduplication - catch concurrent inserts
                    try:
                        await self.db.articles.insert_one(article_doc)
                        new_articles_count += 1
                        logger.info(f"Added article: {title} (score: {ai_result['relevance_score']})")
                    except DuplicateKeyError:
                        # Article was inserted by another process between our check and insert
                        # This can happen if multiple feed fetches run concurrently
                        logger.debug(f"Article already inserted by concurrent process: {title}")
                        continue
                    
                except Exception as e:
                    logger.error(f"Error processing entry from {feed_name}: {e}")
                    continue
            
            # Update feed's last_fetched_at and reset error count
            await self.db.feeds.update_one(
                {"url": feed_url},
                {
                    "$set": {
                        "last_fetched_at": datetime.now(timezone.utc),
                        "error_count": 0
                    }
                }
            )
            
            logger.info(f"Fetched {new_articles_count} new articles from {feed_name}")
            return new_articles_count
            
        except Exception as e:
            logger.error(f"Error fetching feed {feed_name}: {e}")
            
            # Increment error count
            await self.db.feeds.update_one(
                {"url": feed_url},
                {"$inc": {"error_count": 1}}
            )
            
            return 0
    
    async def fetch_all_enabled_feeds(self) -> int:
        """Fetch all enabled feeds and return total new article count."""
        self._ensure_db()
        
        try:
            # Get all enabled feeds
            cursor = self.db.feeds.find({"enabled": True})
            feeds = await cursor.to_list(length=100)
            
            if not feeds:
                logger.warning("No enabled feeds found")
                return 0
            
            total_new_articles = 0
            
            for feed in feeds:
                count = await self.fetch_feed(feed["url"], feed["name"])
                total_new_articles += count
            
            logger.info(f"Total new articles fetched: {total_new_articles}")
            return total_new_articles
            
        except Exception as e:
            logger.error(f"Error fetching all feeds: {e}")
            return 0
    
    async def _get_user_preferences(self) -> UserPreferences:
        self._ensure_db()
        
        prefs_doc = await self.db.preferences.find_one()
        
        if prefs_doc:
            return UserPreferences(**prefs_doc)
        else:
            # Return default preferences
            return UserPreferences(
                interests=["Python", "DevOps", "AI", "Web Development"],
                exclude_topics=["Cryptocurrency", "Blockchain"],
                min_relevance_score=5,
                dark_mode=False
            )


# Global feeder instance
rss_feeder = RSSFeeder()
