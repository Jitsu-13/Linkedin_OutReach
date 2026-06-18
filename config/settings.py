"""
Configuration settings loader.

Merges .env environment variables with config.yaml into a single
validated Pydantic settings object. All code accesses config through
`get_settings()` — no hardcoded values anywhere.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# ── Project root is two levels up from this file (config/settings.py → project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root
load_dotenv(PROJECT_ROOT / ".env")


# ── Nested config models ──────────────────────────────────────

class LinkedInConfig(BaseModel):
    max_requests_per_run: int = 25
    delay_min_seconds: int = 120
    delay_max_seconds: int = 300
    action_delay_min: int = 2
    action_delay_max: int = 8
    typing_delay_min_ms: int = 50
    typing_delay_max_ms: int = 150
    posts_to_like: int = 3
    posts_to_comment: int = 1
    max_errors_before_pause: int = 3
    pause_duration_minutes: int = 30


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    note_max_chars_standard: int = 200
    note_max_chars_premium: int = 300
    default_char_limit: int = 300
    temperature: float = 0.7
    review_temperature: float = 0.3
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"


class SheetsColumnsConfig(BaseModel):
    url: str = "linkedin_url"
    name: str = "name"
    company: str = "company"
    role: str = "role"
    custom_context: str = "custom_context"
    status: str = "status"
    note_used: str = "note_used"
    sent_at: str = "sent_at"
    accepted_at: str = "accepted_at"
    withdrawn_at: str = "withdrawn_at"
    comment_posted: str = "comment_posted"
    posts_liked: str = "posts_liked"


class SheetsConfig(BaseModel):
    spreadsheet_id: str = ""
    worksheet_name: str = "Targets"
    columns: SheetsColumnsConfig = SheetsColumnsConfig()


class FollowupConfig(BaseModel):
    check_interval_days: int = 14
    withdraw_after_days: int = 14


class BrowserConfig(BaseModel):
    headless: bool = False
    user_data_dir: str = "./browser_data"
    viewport_width: int = 1366
    viewport_height: int = 768
    screenshot_on_failure: bool = True
    screenshot_dir: str = "./data/screenshots"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "./data/logs/outreach.log"
    rotation_mb: int = 10
    retention_count: int = 5


# ── Main settings class ───────────────────────────────────────

class Settings(BaseSettings):
    """
    Unified settings: .env vars are loaded as top-level fields,
    config.yaml sections are loaded into nested models.
    """

    # ── From .env ──
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_provider: Optional[str] = Field(default=None, alias="LLM_PROVIDER")
    llm_model: Optional[str] = Field(default=None, alias="LLM_MODEL")

    google_sheets_credentials_file: str = Field(
        default="./credentials/service_account.json",
        alias="GOOGLE_SHEETS_CREDENTIALS_FILE",
    )
    google_sheets_spreadsheet_id: Optional[str] = Field(
        default=None, alias="GOOGLE_SHEETS_SPREADSHEET_ID"
    )

    linkedin_email: str = Field(default="", alias="LINKEDIN_EMAIL")
    linkedin_password: str = Field(default="", alias="LINKEDIN_PASSWORD")

    log_level: Optional[str] = Field(default=None, alias="LOG_LEVEL")

    sender_context: str = Field(
        default="A professional looking to connect and share ideas",
        alias="SENDER_CONTEXT",
    )
    sender_name: str = Field(default="", alias="SENDER_NAME")

    # ── From config.yaml ──
    linkedin: LinkedInConfig = LinkedInConfig()
    llm: LLMConfig = LLMConfig()
    sheets: SheetsConfig = SheetsConfig()
    followup: FollowupConfig = FollowupConfig()
    browser: BrowserConfig = BrowserConfig()
    logging: LoggingConfig = LoggingConfig()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True
        extra = "ignore"


def _load_yaml_config() -> dict:
    """Load config.yaml from the project root."""
    config_path = PROJECT_ROOT / "config" / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Build and cache the unified Settings object.

    Priority: .env overrides > config.yaml > defaults
    """
    yaml_data = _load_yaml_config()

    # Build nested configs from YAML
    linkedin_cfg = LinkedInConfig(**yaml_data.get("linkedin", {}))
    llm_cfg = LLMConfig(**yaml_data.get("llm", {}))
    sheets_cfg = SheetsConfig(**yaml_data.get("sheets", {}))
    followup_cfg = FollowupConfig(**yaml_data.get("followup", {}))
    browser_cfg = BrowserConfig(**yaml_data.get("browser", {}))
    logging_cfg = LoggingConfig(**yaml_data.get("logging", {}))

    # Create settings (env vars auto-loaded by pydantic-settings)
    settings = Settings(
        linkedin=linkedin_cfg,
        llm=llm_cfg,
        sheets=sheets_cfg,
        followup=followup_cfg,
        browser=browser_cfg,
        logging=logging_cfg,
    )

    # .env overrides for LLM provider/model
    if settings.llm_provider:
        settings.llm.provider = settings.llm_provider
    if settings.llm_model:
        settings.llm.model = settings.llm_model

    # .env override for spreadsheet ID
    if settings.google_sheets_spreadsheet_id:
        settings.sheets.spreadsheet_id = settings.google_sheets_spreadsheet_id

    # .env override for log level
    if settings.log_level:
        settings.logging.level = settings.log_level

    return settings
