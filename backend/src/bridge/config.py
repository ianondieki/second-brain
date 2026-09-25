"""Settings (docs/spec/08; REQ-FND-02). Values come from the environment or ``backend/.env``.

Fail closed: a missing or weak secret stops the process at start-up (``get_settings()`` raises), so the app never
runs with a default key. Every variable is documented in ``backend/.env.example``.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIN_SECRET_CHARS = 32

AppEnv = Literal["dev", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: AppEnv = "dev"
    product_name: str = "Bridge (working name)"
    public_base_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    # Proxies whose X-Forwarded-For is trusted for the client IP (login throttling). Comma-separated IPs or CIDRs.
    trusted_proxies: str = "127.0.0.1"

    # PostgreSQL. The API and worker connect as the RLS-bound app role; migrations use the owner role.
    database_url: SecretStr
    database_owner_url: SecretStr | None = None

    # Secrets (required; never defaulted).
    secret_key: SecretStr = Field(description="HMAC key for CSRF tokens and magic-link digests")
    data_encryption_key: SecretStr = Field(description="Base64 32-byte AES-GCM key for TOTP secrets at rest")
    recovery_code_pepper: SecretStr = Field(description="HMAC key for TOTP recovery codes; never rotated")

    # Sessions and auth (docs/spec/08 Auth; retention docs/spec/10: sessions 30 days).
    # __Host- prefix: the browser only accepts them with Secure, Path=/ and no Domain (no cookie tossing).
    session_cookie_name: str = "__Host-bridge_session"
    csrf_cookie_name: str = "__Host-bridge_csrf"
    cookie_secure: bool = True
    session_ttl_days: int = 30
    magic_link_ttl_minutes: int = 15
    step_up_max_age_hours: int = 12
    login_attempts_per_minute: int = 5

    # Email (ADR-004): Mailpit over SMTP in dev, CI and staging; Postmark only in production (after G7, sender-domain
    # DNS); fake in unit tests. bridge.notifications.email.provider_from_settings enforces this.
    email_provider: Literal["smtp", "postmark", "fake"] = "smtp"
    email_from: str = "Bridge <no-reply@bridge.localhost>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    postmark_server_token: SecretStr | None = None
    postmark_message_stream: str = "outbound"

    # Feature flags (docs/spec/10: default false until the legal gate).
    feature_tier2_enabled: bool = False
    feature_deals_enabled: bool = False

    # Config files.
    plans_file: Path = BACKEND_DIR / "config" / "plans.yaml"
    consents_file: Path = BACKEND_DIR / "config" / "consents.yaml"

    @model_validator(mode="after")
    def _fail_closed(self) -> Settings:
        problems: list[str] = []
        for name in ("secret_key", "data_encryption_key", "recovery_code_pepper"):
            value: SecretStr = getattr(self, name)
            if len(value.get_secret_value()) < MIN_SECRET_CHARS:
                problems.append(f"{name.upper()} must be at least {MIN_SECRET_CHARS} characters")
        try:
            if len(base64.b64decode(self.data_encryption_key.get_secret_value(), validate=True)) != 32:
                problems.append("DATA_ENCRYPTION_KEY must be base64 of exactly 32 bytes")
        except ValueError:
            problems.append("DATA_ENCRYPTION_KEY must be base64 of exactly 32 bytes")
        if self.email_provider == "postmark" and not self.postmark_server_token:
            problems.append("POSTMARK_SERVER_TOKEN is required when EMAIL_PROVIDER=postmark")
        if self.app_env == "production":
            if self.email_provider != "postmark":
                problems.append("production sends email through Postmark only (EMAIL_PROVIDER=postmark)")
            if not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL must be https in production")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise ValueError("; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings; raises (fails closed) when a required value is missing or weak."""
    return Settings()  # values come from the environment
