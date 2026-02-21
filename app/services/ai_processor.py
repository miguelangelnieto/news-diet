import asyncio
import httpx
import logging
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError
from app.config import settings
from app.models import UserPreferences

logger = logging.getLogger(__name__)


class AIProcessor:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.ollama_base_url,
            api_key="not-needed",  # Ollama doesn't require API key
            timeout=settings.ollama_timeout,
            http_client=httpx.AsyncClient(timeout=settings.ollama_timeout)
        )
        self.model = settings.ollama_model
    
    async def ensure_model_available(self) -> bool:
        """Check if model is pulled, pull it if not. Returns True if ready."""
        try:
            # Check if model exists via Ollama API
            ollama_url = settings.ollama_base_url.replace("/v1", "")
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{ollama_url}/api/tags")
                
                if response.status_code == 200:
                    models_data = response.json()
                    models = models_data.get("models", [])
                    model_names = [m.get("name", "") for m in models]
                    
                    if self.model in model_names:
                        logger.info(f"Model {self.model} is already available")
                        return True
                    
                    # Model not found, trigger pull
                    logger.info(f"Model {self.model} not found. Starting pull...")
                    pull_response = await client.post(
                        f"{ollama_url}/api/pull",
                        json={"name": self.model},
                        timeout=600  # Model pull can take several minutes
                    )
                    
                    if pull_response.status_code == 200:
                        logger.info(f"Successfully pulled model {self.model}")
                        return True
                    else:
                        logger.error(f"Failed to pull model: {pull_response.text}")
                        return False
                else:
                    logger.error(f"Failed to check models: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error ensuring model availability: {e}")
            return False
    
    async def summarize_article(self, title: str, content: str) -> str:
        """Generate exactly 4 informative sentences in the article's original language."""
        try:
            prompt = f"""Summarize this news article in EXACTLY 4 informative sentences. 
Include only the key facts and main points.

IMPORTANT: 
- Write the summary in the SAME LANGUAGE as the original article.
- NO PREAMBLE like "Here is a summary". Start directly.
- DO NOT exceed 4 sentences.

Title: {title}
Content: {content[:1000]}

Summary:"""
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a concise tech news summarizer. Output EXACTLY 4 sentences. NO introduction or meta-commentary. ALWAYS use the same language as the input article."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=250
            )
            
            summary = response.choices[0].message.content.strip()
            
            # Post-process: remove common preambles if LLM still adds them
            unwanted_prefixes = [
                "here is a summary",
                "here's a summary",
                "this article",
                "the article",
                "summary:",
            ]
            summary_lower = summary.lower()
            for prefix in unwanted_prefixes:
                if summary_lower.startswith(prefix):
                    if ':' in summary[:50]:
                        summary = summary.split(':', 1)[1].strip()
                    break
            
            # Final safety check: if LLM ignored the 4-sentence limit, we take the first 4.
            # This prevents UI layout shifts.
            sentences = [s.strip() for s in summary.split('.') if s.strip()]
            if len(sentences) > 4:
                summary = '. '.join(sentences[:4]) + '.'
            
            return summary
            
        except (APIConnectionError, APITimeoutError) as e:
            logger.warning(f"AI service unavailable for summarization: {e}")
            return "Summary unavailable - AI service temporarily offline."
        except Exception as e:
            logger.error(f"Unexpected error summarizing article: {type(e).__name__}: {e}")
            return "Summary generation failed."
    
    async def score_relevance(
        self, 
        title: str, 
        content: str, 
        preferences: UserPreferences
    ) -> tuple[int, list[str]]:
        """
        Hybrid scoring: AI extracts topic tags, code calculates score.
        
        Small LLMs struggle with consistent numeric scoring, so we use a hybrid approach:
        - AI identifies matching topics (what it's good at)
        - Code assigns score based on tag count (reliable and predictable)
        
        Scoring: 0 tags=1-3, 1 tag=4-6, 2 tags=6-8, 3+ tags=8-10.
        Quality assessment (low/medium/high) adjusts within range.
        """
        try:
            # Build context from user preferences
            interests_str = ", ".join(preferences.interests) if preferences.interests else "general tech news"
            exclude_str = ", ".join(preferences.exclude_topics) if preferences.exclude_topics else "none"
            
            # Simplified prompt - just ask for tags and basic quality assessment
            prompt = f"""Analyze this article for a reader interested in: {interests_str}
Topics to AVOID: {exclude_str}

Your task:
1. Identify which topics from the interest list this article is CLEARLY about (main focus, not just mentioned)
2. Assess the article quality: low, medium, or high

Available topics: {interests_str}

Article:
Title: {title}
Content: {content[:800]}

IMPORTANT:
- Only tag topics that are a PRIMARY focus of the article
- If article is about excluded topics, return EXCLUDED
- Return 0-3 tags maximum
- Most articles should have 0-1 tags

Format:
Tags: [tag1, tag2] OR Tags: [] OR Tags: EXCLUDED
Quality: low OR Quality: medium OR Quality: high"""
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"You are a topic tagger. Extract relevant topics from articles. Only use these exact topics: {interests_str}. Be selective - most articles should get 0-1 tags."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=100
            )
            
            result = response.choices[0].message.content.strip()
            
            # Parse tags
            tags = []
            quality = "medium"  # Default
            is_excluded = False
            
            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("Tags:"):
                    tags_str = line.split(":", 1)[1].strip()
                    if tags_str.upper() == "EXCLUDED":
                        is_excluded = True
                        tags = []
                    elif tags_str.lower() in ["none", "n/a", "na", "[]", ""]:
                        tags = []
                    else:
                        raw_tags = [t.strip().strip("[]\"'") for t in tags_str.split(",")]
                        # Filter tags to only include those in user's interests (case-insensitive match)
                        interests_lower = {i.lower(): i for i in preferences.interests} if preferences.interests else {}
                        # Use original capitalization from interests list
                        tags = [interests_lower[t.lower()] for t in raw_tags if t.lower() in interests_lower][:3]
                elif line.startswith("Quality:"):
                    quality_str = line.split(":")[1].strip().lower()
                    if quality_str in ["low", "medium", "high"]:
                        quality = quality_str
            
            # PROGRAMMATIC SCORING based on tags
            if is_excluded:
                # Article is about excluded topic
                score = 0
            elif len(tags) == 0:
                # No matching interests - low relevance
                if quality == "high":
                    score = 3  # Maybe tangentially interesting
                elif quality == "medium":
                    score = 2
                else:
                    score = 1
            elif len(tags) == 1:
                # One matching interest - moderate relevance
                if quality == "high":
                    score = 6  # Good coverage of one interest
                elif quality == "medium":
                    score = 5  # Standard coverage
                else:
                    score = 4  # Superficial coverage
            elif len(tags) == 2:
                # Two matching interests - high relevance
                if quality == "high":
                    score = 8  # Excellent multi-topic article
                elif quality == "medium":
                    score = 7  # Good multi-topic coverage
                else:
                    score = 6  # Multiple topics but shallow
            else:  # 3+ tags
                # Three+ matching interests - exceptional relevance
                if quality == "high":
                    score = 10  # Perfect match
                elif quality == "medium":
                    score = 9  # Excellent coverage
                else:
                    score = 8  # Good but not deep
            
            return score, tags
            
        except (APIConnectionError, APITimeoutError) as e:
            logger.warning(f"AI service unavailable for scoring: {e}")
            return 5, []  # Default: medium relevance when AI unavailable
        except Exception as e:
            logger.error(f"Unexpected error scoring article: {type(e).__name__}: {e}")
            return 5, []  # Default: medium relevance, no tags
    
    async def process_article(
        self,
        title: str,
        content: str,
        preferences: UserPreferences
    ) -> dict:
        """Run summary and scoring in parallel, return dict with both results."""
        # Run both operations in parallel for better performance
        summary, (score, tags) = await asyncio.gather(
            self.summarize_article(title, content),
            self.score_relevance(title, content, preferences)
        )
        
        return {
            "summary": summary,
            "relevance_score": score,
            "tags": tags
        }


# Global AI processor instance
ai_processor = AIProcessor()
