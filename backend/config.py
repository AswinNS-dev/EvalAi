"""
backend/config.py
Loads all environment variables and exports a typed Settings object.
Falls back gracefully when optional services (Snowflake, Twilio) are absent.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Groq ──────────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_api_key_slide: str = ""
    groq_api_key_repo: str = ""
    groq_api_key_impact: str = ""
    groq_api_key_tech: str = ""
    groq_api_key_claim: str = ""
    groq_api_key_chief: str = ""

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = ""

    # ── HuggingFace ───────────────────────────────────────────────────────────
    huggingface_api_token: str = ""

    # ── GitHub ────────────────────────────────────────────────────────────────
    github_token: str = ""

    # ── Snowflake ─────────────────────────────────────────────────────────────
    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_password: str = ""
    snowflake_warehouse: str = "COMPUTE_WH"
    snowflake_database: str = "EVALAI_DB"
    snowflake_schema: str = "PUBLIC"

    # ── SQLite fallback ───────────────────────────────────────────────────────
    sqlite_fallback_path: str = "data/evalai.db"

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    frontend_url: str = "http://localhost:3000"

    # ── Derived flags ─────────────────────────────────────────────────────────
    @property
    def snowflake_available(self) -> bool:
        return bool(self.snowflake_account and self.snowflake_user and self.snowflake_password)

    @property
    def twilio_available(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_phone_number)

    @property
    def groq_available(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def openai_available(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Convenient module-level alias
settings = get_settings()
