import asyncio
import httpx
import logging
import re
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError
from app.config import settings
from app.models import UserPreferences

logger = logging.getLogger(__name__)


class AIProcessor:
    def __init__(self):
        # Configure client based on provider
        if settings.llm_provider == "openrouter":
            self.client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=settings.openrouter_api_key,
                timeout=settings.openrouter_timeout,
                http_client=httpx.AsyncClient(timeout=settings.openrouter_timeout)
            )
            self.model = settings.openrouter_model
        else:
            # Default to Ollama
            self.client = AsyncOpenAI(
                base_url=settings.ollama_base_url,
                api_key="not-needed",
                timeout=settings.ollama_timeout,
                http_client=httpx.AsyncClient(timeout=settings.ollama_timeout)
            )
            self.model = settings.ollama_model
    
    async def ensure_model_available(self) -> bool:
        """Check if model is pulled, pull it if not. Returns True if ready. 
        Only applicable for local Ollama deployments."""
        if settings.llm_provider != "ollama":
            return True
            
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
Include only the key facts, developments, and main points.

IMPORTANT: 
- Language: ALWAYS write the summary in the SAME LANGUAGE as the original article.
- Structure: Start directly, NO preamble (e.g., "This article describes...", "Summary:").
- Constraint: DO NOT exceed 4 sentences. Make each sentence high-signal.

Title: {title}
Content: {content[:1500]}

Summary:"""
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a professional news editor. You produce high-signal, concise summaries. ALWAYS use the same language as the input article. Output EXACTLY 4 sentences."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=350
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
            sentences = [s.strip() for s in summary.split('.') if s.strip()]
            if len(sentences) > 4:
                summary = '. '.join(sentences[:4]) + '.'
            elif len(sentences) > 0 and not summary.endswith('.'):
                summary += '.'
            
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
        Hybrid scoring: AI extracts tags and suggests a score based on a rubric.
        
        Rubric:
        - 1-2: Irrelevant or purely promotional/spam.
        - 3-4: Tangentially related, low interest.
        - 5-6: Generally related to user interests but not a perfect match.
        - 7-8: Directly matches one or more interests, good quality.
        - 9-10: Perfect match, high-signal, must-read for the user.
        """
        try:
            interests_list = preferences.interests if preferences.interests else []
            interests_str = ", ".join(interests_list) if interests_list else "general topics"
            exclude_str = ", ".join(preferences.exclude_topics) if preferences.exclude_topics else "none"
            
            prompt = f"""Analyze this news article for relevance against the user's interests.

USER INTERESTS: {interests_str}
EXCLUDED TOPICS: {exclude_str}

ARTICLE:
Title: {title}
Content: {content[:1500]}

SCORING RUBRIC (1-10 scale):
10: Essential. Perfect match for multiple interests, high quality and depth.
8: High Relevance. Solidly covers at least one interest.
6: Moderate. Generally related to user interests but not a perfect match.
4: Low. Tangentially related or low quality.
1: Irrelevant or Excluded. Matches excluded topics or is spam/ad.

OUTPUT FORMAT:
Reasoning: <1 short sentence>
Tags: <comma_separated_matches_from_USER_INTERESTS_list_ONLY>
Score: <integer_1_to_10>
"""
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict and objective news classifier. You ONLY select tags from the USER INTERESTS list. Be objective and critical in your scoring."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200
            )
            
            result = response.choices[0].message.content.strip()
            
            # Parse result
            tags = []
            ai_score = 5
            
            # Case-insensitive lookup map
            interests_map = {i.lower(): i for i in interests_list}
            
            for line in result.split("\n"):
                line = line.strip()
                if line.lower().startswith("tags:"):
                    tags_part = line.split(":", 1)[1].strip()
                    if "excluded" in tags_part.lower() or "none" in tags_part.lower():
                        tags = []
                    else:
                        raw_candidates = [t.strip().strip("[]\"'") for t in tags_part.split(",")]
                        for raw in raw_candidates:
                            if raw.lower() in interests_map:
                                tags.append(interests_map[raw_lower])
                            
                elif line.lower().startswith("score:"):
                    score_part = line.split(":", 1)[1].strip()
                    try:
                        # Extract first number found in the score line
                        match = re.search(r'(\d+)', score_part)
                        if match:
                            ai_score = int(match.group(1))
                    except ValueError:
                        pass
            
            # Final scoring logic: we trust the AI score more for larger models, 
            # but we still cap it based on tags for consistency if no interests matched.
            tags = list(dict.fromkeys(tags))[:3]
            
            if len(tags) == 0 and ai_score > 6:
                # If no specific interests matched but score is high, 
                # maybe it's generally good news. Moderate it slightly.
                final_score = 5
            elif len(tags) > 0 and ai_score < 6:
                # If interests matched but AI scored it low, trust the AI (maybe poor quality).
                final_score = ai_score
            else:
                final_score = ai_score
                
            # Clamp between 0 and 10
            final_score = max(0, min(10, final_score))
            
            return final_score, tags
            
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
