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
    enable_live_data: bool = True

    # Routing network. "real" routes on the actual drivable OpenStreetMap road
    # network (OSMnx + NetworkX); "simulated" uses the seeded DB road graph
    # (used by the automated test-suite offline). Never silently falls back:
    # a failing OSM provider surfaces an explicit error.
    routing_network: str = "real"

    # OSM/Overpass response cache folder (persistent, survives restarts) and
    # the max N road graphs kept in process memory (LRU).
    osm_graph_cache_dir: str = ".cache/road_graphs"
    osm_graph_memory_entries: int = 3

    # Routing corridor / span limits for graph downloads.
    route_max_span_deg: float = 2.0

    # CORS (comma-separated list of frontend origins)
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    # AI orchestrator settings (Groq)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_enabled: bool = True
    groq_max_tool_iterations: int = 6
    groq_max_tool_calls: int = 10
    groq_max_output_tokens: int = 2048
    groq_temperature: float = 0.3
    groq_timeout_seconds: float = 60.0
    groq_history_window: int = 10

    # Legacy Gemini settings are retained only for backwards-compatible test
    # imports and old local environment files. They are never selected by the
    # production client.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_enabled: bool = True
    gemini_max_tool_iterations: int = 6   # model/tool round-trips per request
    gemini_max_tool_calls: int = 10       # tool executions per request
    gemini_max_output_tokens: int = 2048
    gemini_temperature: float = 0.3
    gemini_timeout_seconds: float = 60.0
    gemini_history_window: int = 10       # recent conversation messages sent to the model

    @property
    def ai_ready(self) -> bool:
        """True when the configured Groq integration has a key."""
        return bool(self.groq_enabled and self.groq_api_key.strip())

    @property
    def gemini_ready(self) -> bool:
        """Legacy compatibility alias; Groq remains the active provider."""
        return self.ai_ready or bool(self.gemini_enabled and self.gemini_api_key.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse the comma-separated CORS origin string into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()


settings = get_settings()
