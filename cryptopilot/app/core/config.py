"""Cấu hình ứng dụng — load từ .env qua pydantic-settings.

Mọi secret (JWT_SECRET, API keys) đều đọc từ .env, KHÔNG hardcode.
Tên field khớp với các key trong .env.example.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App / Auth ──
    JWT_SECRET: str = "change-me-in-env"  # BẮT BUỘC đặt trong .env ở production
    JWT_EXPIRE_MINUTES: int = 60
    JWT_ALGORITHM: str = "HS256"

    # ── Database ──
    DATABASE_URL: str = "sqlite:///./cryptopilot.db"

    # ── CoinGecko (market data) ──
    COINGECKO_BASE_URL: str = "https://api.coingecko.com/api/v3"
    COINGECKO_DEMO_KEY: str = ""

    # ── Google Gemini (AI Agent) ──
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # ── CryptoPanic (news) ──
    CRYPTOPANIC_BASE_URL: str = "https://cryptopanic.com/api/developer/v2"
    CRYPTOPANIC_TOKEN: str = ""


# Singleton — import ở mọi nơi: `from app.core.config import settings`
settings = Settings()
