"""Application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """ReliefMesh backend settings.

    Every field can be overridden through environment variables (the variable
    name matches the field name, case-insensitive) or a `.env` file in the
    backend directory.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "ReliefMesh API"
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    # API
    api_v1_prefix: str = "/api/v1"

    # Platform behaviour. The entire initial dataset is a simulated disaster
    # scenario; `data_mode` makes this explicit in every relevant response.
    data_mode: str = "SIMULATED"

    # Database
    database_url: str = "sqlite:///./reliefmesh.db"

    # Startup behaviour
    auto_init_db: bool = True
    auto_seed: bool = True

    # CORS (comma-separated list of frontend origins)
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    # Gemini AI orchestrator (Phase 3). The API key lives ONLY in `.env`;
    # it is never logged, returned or stored in database records.
    gemini_api_key: str = ""  # empty -> AI endpoints fail with a clear config error
    gemini_model: str = "gemini-3.8-flash"
    gemini_enabled: bool = True
    gemini_max_tool_iterations: int = 6   # model/tool round-trips per request
    gemini_max_tool_calls: int = 10       # tool executions per request
    gemini_max_output_tokens: int = 2048
    gemini_temperature: float = 0.3
    gemini_timeout_seconds: float = 60.0
    gemini_history_window: int = 10       # recent conversation messages sent to the model

    @property
    def gemini_ready(self) -> bool:
        """True when a non-empty API key is configured and AI is enabled."""
        return bool(self.gemini_enabled and self.gemini_api_key.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse the comma-separated CORS origin string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()


settings = get_settings()
