"""Configuration for Tokenxygen."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


DATA_DIR = Path(os.environ.get("TOKENDATA_DIR", Path.home() / ".tokenxygen"))


def today_start_timestamp() -> float:
    """Return Unix timestamp for start of today (UTC). Used by analytics and budget."""
    today = datetime.date.today()
    return datetime.datetime.combine(today, datetime.time.min).timestamp()


# Cache defaults
DEFAULT_CACHE_SIMILARITY_THRESHOLD = 0.92
DEFAULT_CACHE_MAX_ENTRIES = 10_000
DEFAULT_CACHE_TTL_SECONDS = 86400  # 24 hours


class CacheConfig(BaseSettings):
    """Semantic cache settings."""

    enabled: bool = True
    similarity_threshold: float = DEFAULT_CACHE_SIMILARITY_THRESHOLD
    max_entries: int = DEFAULT_CACHE_MAX_ENTRIES
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    db_path: str = str(DATA_DIR / "cache.db")


class CompressConfig(BaseSettings):
    """Prompt compression settings."""

    enabled: bool = True
    aggressiveness: float = Field(default=0.3, ge=0.0, le=1.0)
    # 0.0 = no compression, 1.0 = maximum compression
    preserve_instructions: bool = True
    max_context_tokens: int = 16_000


class RouterConfig(BaseSettings):
    """Model routing settings."""

    enabled: bool = True
    # Simple routing: if estimated tokens < threshold, use cheap model
    simple_threshold: int = 500
    cheap_model: str = "gpt-4o-mini"
    expensive_model: str = "gpt-4o"


class BudgetConfig(BaseSettings):
    """Budget guard settings."""

    daily_limit_usd: float = 10.0
    alert_threshold: float = 0.8  # alert at 80%


class AnalyticsConfig(BaseSettings):
    """Analytics / tracking settings."""

    enabled: bool = True
    db_path: str = str(DATA_DIR / "analytics.db")


class ProxyConfig(BaseSettings):
    """Proxy server settings."""

    host: str = "127.0.0.1"
    port: int = 8420
    # Upstream API base URL (where to forward unoptimized requests)
    upstream_base_url: str = "https://api.openai.com/v1"
    api_key: str = Field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    log_level: str = "INFO"


class Settings(BaseSettings):
    """Root settings."""

    cache: CacheConfig = CacheConfig()
    compress: CompressConfig = CompressConfig()
    router: RouterConfig = RouterConfig()
    budget: BudgetConfig = BudgetConfig()
    analytics: AnalyticsConfig = AnalyticsConfig()
    proxy: ProxyConfig = ProxyConfig()

    def ensure_dirs(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
