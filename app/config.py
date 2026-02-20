from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MongoDB Configuration
    mongodb_url: str = "mongodb://mongo:27017"
    mongodb_db: str = "newsdiet"
    
    # Ollama Configuration
    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: int = 120
    
    # Application Configuration
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = False
    
    # RSS Fetch Configuration
    rss_fetch_interval_hours: int = 1
    
    # Feed Management
    delete_articles_on_feed_removal: bool = True
    
    # Logging
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# Global settings instance
settings = Settings()
