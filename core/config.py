"""
Javris – Centralised configuration using pydantic-settings.
Reads from .env automatically.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class JavrisConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── AI ────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""        # legacy single-key fallback
    google_api_key_1: str = ""      # key pool slot 1
    google_api_key_2: str = ""      # key pool slot 2
    google_api_key_3: str = ""      # key pool slot 3
    ollama_base_url: str = "http://localhost:11434"

    # ── Fast inference providers ──────────────────────────────
    groq_api_key: str = ""          # Groq — fastest open-source inference
    cerebras_api_key: str = ""      # Cerebras — ultra-fast silicon

    javris_primary_model: Literal["claude", "ollama", "openai", "gemini", "groq", "cerebras"] = "groq"
    javris_claude_model: str = "claude-sonnet-4-6"
    javris_ollama_model: str = "phi3:latest"

    # ── Voice ─────────────────────────────────────────────────
    tts_engine: Literal["elevenlabs", "edge_tts", "pyttsx3"] = "edge_tts"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    stt_engine: Literal["whisper_local", "whisper_api", "google"] = "whisper_local"
    whisper_model: str = "base"
    wake_word: str = "jarvis"
    porcupine_api_key: str = ""

    # ── Firebase ──────────────────────────────────────────────
    firebase_project_id: str = ""
    firebase_credentials_path: str = "firebase-credentials.json"
    firebase_credentials_base64: str = ""

    # ── Skills — Weather ──────────────────────────────────────
    weather_api_key: str = ""          # OpenWeatherMap
    aqicn_api_key: str = ""            # Air quality index
    aqicn_base_url: str = "https://api.waqi.info"
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"

    # ── Skills — News ─────────────────────────────────────────
    news_api_key: str = ""             # legacy NewsAPI.org
    gnews_api_key: str = ""            # GNews — primary source
    gnews_base_url: str = "https://gnews.io/api/v4"
    marketaux_api_key: str = ""        # Finance/market news
    marketaux_base_url: str = "https://api.marketaux.com/v1"
    newsdata_api_key: str = ""         # NewsData.io backup
    newsdata_base_url: str = "https://newsdata.io/api/1"
    inshorts_base_url: str = "https://inshortsapi.vercel.app"
    spaceflight_base_url: str = "https://api.spaceflightnewsapi.net/v4"

    # ── Skills — Finance / Trading ────────────────────────────
    alpha_vantage_api_key: str = ""
    finnhub_api_key: str = ""
    fmp_api_key: str = ""              # Financial Modeling Prep
    fred_base_url: str = "https://api.stlouisfed.org/fred"

    # ── Skills — Search ───────────────────────────────────────
    serpapi_key: str = ""
    tavily_api_key: str = ""             # Tavily search (from openclaw)
    brave_api_key: str = ""              # Brave search (from openclaw)

    # ── Skills — GitHub ───────────────────────────────────────
    github_token: str = ""               # GitHub personal access token

    # ── Skills — Notion ──────────────────────────────────────
    notion_api_key: str = ""             # Notion internal integration token (ntn_...)
    notion_client_id: str = ""           # Notion OAuth client ID
    notion_client_secret: str = ""       # Notion OAuth client secret
    notion_redirect_uri: str = "http://127.0.0.1:8000/auth/notion/callback"

    # ── Skills — Obsidian ────────────────────────────────────
    obsidian_vault_path: str = ""        # Absolute path to Obsidian vault folder

    # ── Skills — Discord (bot API, separate from webhook) ────
    discord_bot_token: str = ""          # Discord bot token (for reading messages)
    discord_channel_id: str = ""         # Default channel ID for discord bot

    # ── Skills — Music ────────────────────────────────────────
    tastedive_api_key: str = ""
    musicbrainz_base_url: str = "https://musicbrainz.org/ws/2"
    lrclib_base_url: str = "https://lrclib.net/api"
    radio_browser_base_url: str = "https://de1.api.radio-browser.info/json"

    # ── Skills — Mail ─────────────────────────────────────────
    disify_api_key: str = ""

    # ── Google OAuth ──────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # ── Server ────────────────────────────────────────────────
    javris_host: str = "127.0.0.1"
    javris_port: int = 8000
    javris_secret_key: str = "change_me"
    javris_debug: bool = False
    javris_api_token: str = ""
    javris_auth_enabled: bool = False
    javris_permission_mode: Literal["adaptive", "strict", "open"] = "adaptive"
    javris_local_only: bool = True
    javris_autonomy_enabled: bool = False

    # ── Notifications ─────────────────────────────────────────
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Storage ───────────────────────────────────────────────
    local_db_path: str = "data/javris.db"

    # Supabase — accepts both plain and NEXT_PUBLIC_ prefixed names
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_url", "next_public_supabase_url"),
    )
    supabase_anon_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "supabase_anon_key",
            "next_public_supabase_publishable_key",
            "next_public_supabase_anon_key",
        ),
    )

    # Local storage root (audio, images, logs, temp)
    jarvis_data_dir: str = "jarvis_data"

    # Degoo cold-storage auto-sync folder (Degoo desktop watches this)
    degoo_sync_dir: str = "jarvis_data/degoo_sync"

    # Storage behaviour
    storage_auto_sync: bool = True          # sync to Supabase on every chat turn
    storage_cold_threshold_mb: int = 10     # files larger than this go to Degoo

    # ── Logging ───────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/javris.log"

    # ── Derived paths (not from env) ──────────────────────────
    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def data_dir(self) -> Path:
        p = BASE_DIR / "data"
        p.mkdir(exist_ok=True)
        return p

    @property
    def logs_dir(self) -> Path:
        p = BASE_DIR / "logs"
        p.mkdir(exist_ok=True)
        return p

    @property
    def jarvis_data_path(self) -> Path:
        p = BASE_DIR / self.jarvis_data_dir
        p.mkdir(exist_ok=True)
        return p

    @property
    def degoo_sync_path(self) -> Path:
        p = BASE_DIR / self.degoo_sync_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def firebase_creds_path(self) -> Path:
        return BASE_DIR / self.firebase_credentials_path

    @field_validator("log_level")
    @classmethod
    def upper_log_level(cls, v: str) -> str:
        return v.upper()


@lru_cache(maxsize=1)
def get_config() -> JavrisConfig:
    return JavrisConfig()
