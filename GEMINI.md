# GEMINI.md - Project Context: News Diet

## Project Overview
**News Diet** is an AI-powered RSS news aggregator inspired by Google Reader. It's designed to be self-hosted, privacy-focused, and highly customizable. The core value proposition is using Large Language Models (LLMs) to automatically score the relevance of news articles based on user-defined interests and generate concise, 4-sentence summaries.

### Main Technologies
- **Backend:** Python 3.11+ with **FastAPI** (async framework).
- **Database:** **MongoDB** (accessed via `motor` for async operations).
- **Frontend:** **Jinja2** templates, **TailwindCSS** (styling), and **HTMX** (dynamic UI without full page reloads).
- **AI/LLM:** Integrated with **Ollama** (local) or **OpenRouter** (cloud) via the `openai` Python client.
- **Task Scheduling:** **APScheduler** for periodic RSS feed fetching.
- **RSS Parsing:** `feedparser`, `trafilatura` (content extraction), and `BeautifulSoup4`.
- **Containerization:** **Docker** and **Docker Compose**.

### Architecture
The project follows a service-oriented architecture:
- `app/main.py`: Entry point, FastAPI app initialization, and route definitions.
- `app/config.py`: Settings management using `pydantic-settings`.
- `app/database.py`: MongoDB connection management and database access.
- `app/models.py`: Pydantic models for data validation and API schemas.
- `app/services/ai_processor.py`: Logic for article relevance scoring and summarization.
- `app/services/feeder.py`: RSS feed fetching, parsing, and article deduplication.
- `app/services/scheduler.py`: Background job management for automatic updates.
- `app/templates/`: HTML templates for the dashboard, reader, and management pages.
- `app/static/`: Static assets including icons and a service worker.

---

## Building and Running

### Prerequisites
- Docker and Docker Compose (recommended).
- Python 3.11+ (for local development).
- MongoDB (local or via Docker).
- Ollama (optional, for local AI processing).

### Docker (Primary Method)
1.  **Configure Environment:**
    ```bash
    cp .env.example .env
    cp docker-compose.yml.example docker-compose.yml
    ```
    Edit `.env` to set your `LLM_PROVIDER` (ollama or openrouter) and relevant keys/URLs.
2.  **Start Services:**
    ```bash
    docker compose up -d
    ```
3.  **Access App:** `http://localhost:8000`

### Local Development
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Run Application:**
    ```bash
    uvicorn app.main:app --reload
    ```
    Ensure a MongoDB instance is running and accessible via the `MONGODB_URL` in your `.env`.

### Testing
- **Run Tests:** `pytest`
- Tests are located in the `tests/` directory and use `pytest-asyncio`.

---

## Development Conventions

### AI Interaction
- **Summarization:** The `ai_processor.py` is configured to generate exactly 4-sentence summaries in the article's original language.
- **Scoring:** Articles are scored from 0-10. The AI identifies matching interests and quality; the final score is calculated in Python.
- **Model Management:** If using Ollama, the application attempts to automatically pull the required model (default: `gemma3n:e4b`) on startup.

### RSS & Data Handling
- **Deduplication:** Articles are deduplicated by URL at three levels: application check, database unique index, and race condition handling during insertion.
- **Content Extraction:** `trafilatura` is used for high-quality full-text extraction from article URLs.
- **Sanitization:** Strict HTML sanitization is performed on extracted content to prevent XSS (see `feeder.py`).

### UI/UX
- **HTMX:** Used for "Mark as Read", "Star", and "Refresh" actions to provide a responsive feel without reloading the page.
- **Theming:** Uses the **Catppuccin** color scheme with support for both light and dark modes (persisted in user preferences).
- **Responsive:** Designed to work well on both desktop and mobile.

### Coding Style
- **Async First:** Almost all I/O operations (database, AI, HTTP requests) are `async`.
- **Typing:** Extensive use of Python type hints and Pydantic models.
- **Logging:** Structured logging is used throughout the application; log level is configurable via `.env`.

---

## Key Files Summary
- `app/main.py`: Routes and app lifecycle.
- `app/models.py`: Core data structures (Feed, Article, Preferences).
- `app/services/ai_processor.py`: LLM prompt engineering and scoring logic.
- `app/services/feeder.py`: Feed fetching and HTML cleaning logic.
- `app/config.py`: Centralized environment configuration.
- `app/templates/index.html`: Main dashboard template.
