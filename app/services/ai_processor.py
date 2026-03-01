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
Content: {content[:12000]}

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
            
            # Final safety check: if LLM ignored the 4-sentence limit, take the first 4.
            # Use a regex that splits on sentence-ending punctuation followed by whitespace,
            # which avoids false splits on abbreviations like "Dr." or "U.S.".
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', summary) if s.strip()]
            if len(sentences) > 4:
                summary = ' '.join(sentences[:4])
                if not summary[-1] in '.!?':
                    summary += '.'
            elif len(sentences) > 0 and summary[-1] not in '.!?':
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
        Scores relevance based on a simplified AI analysis and deterministic scoring logic.
        The AI's job is to identify matching interests, excluded topics, and assess quality.
        The final score is calculated in Python based on this analysis.
        """
        try:
            interests_list = preferences.interests if preferences.interests else []
            interests_str = ", ".join(interests_list) if interests_list else "none"
            exclude_str = ", ".join(preferences.exclude_topics) if preferences.exclude_topics else "none"

            prompt = f"""Analyze this news article against the user's preferences.

USER INTERESTS: {interests_str}
EXCLUDED TOPICS: {exclude_str}

ARTICLE TITLE: {title}
ARTICLE CONTENT: {content[:12000]}

Your task is to identify three things:
1.  Matching Interests: Which topics from USER INTERESTS are EXPLICITLY discussed in this article?
2.  Excluded Topics: Does the article mention any EXCLUDED TOPICS?
3.  Quality: Assess the article's quality (not its relevance). Is it High, Medium, or Low?
    - High: In-depth analysis, original reporting.
    - Medium: Standard news report.
    - Low: Clickbait, promotional, shallow.

CRITICAL INSTRUCTIONS:
- ONLY list interests that are explicitly mentioned and discussed.
- If no user interests are explicitly discussed, output "none".

Respond in this exact format, with each field on a new line:
Tags: <list matching interests, or "none">
Excluded: <list any excluded topics found, or "none">
Quality: <High, Medium, or Low>"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict news classifier. Your job is to extract topics based ONLY on explicit content. Do not infer interests that are not explicitly mentioned. Only use the provided tags."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=200
            )

            result = response.choices[0].message.content.strip().lower()

            # --- Parsing Logic ---
            tags = []
            has_excluded = False
            quality_modifier = 0

            # Case-insensitive lookup map for user interests
            interests_map = {i.lower(): i for i in interests_list}
            
            # 1. Parse Tags
            tags_match = re.search(r'tags:\s*(.*)', result)
            if tags_match:
                tags_part = tags_match.group(1).strip()
                if tags_part and "none" not in tags_part:
                    raw_candidates = re.split(r'[,;]|\s+and\s+', tags_part)
                    for raw in raw_candidates:
                        cleaned = raw.strip().strip("[]\"'()").lower()
                        if cleaned in interests_map:
                            tags.append(interests_map[cleaned])
            
            # 2. Parse Excluded Topics
            excluded_match = re.search(r'excluded:\s*(.*)', result)
            if excluded_match:
                excluded_part = excluded_match.group(1).strip()
                if excluded_part and "none" not in excluded_part:
                    has_excluded = True

            # 3. Parse Quality
            quality_match = re.search(r'quality:.*?(high|medium|low)', result)
            if quality_match:
                quality = quality_match.group(1).strip()
                if quality == "high":
                    quality_modifier = 1
                elif quality == "low":
                    quality_modifier = -1

            # --- Scoring Logic ---
            final_score = 0
            # Remove duplicate tags while preserving order
            tags = list(dict.fromkeys(tags))

            # If any excluded topic is present, the article is irrelevant.
            if has_excluded:
                final_score = 0
                # Clear tags as they are irrelevant if topic is excluded
                tags = []
            else:
                # Base score on number of matching interests
                if len(tags) == 0:
                    final_score = 1
                elif len(tags) == 1:
                    final_score = 5
                elif len(tags) == 2:
                    final_score = 8
                elif len(tags) >= 3:
                    final_score = 10
                
                # Apply quality modifier
                final_score += quality_modifier

            # Clamp score to be between 0 and 10
            final_score = max(0, min(10, final_score))
            
            # If score is 0, do not return any tags
            if final_score == 0:
                tags = []

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
