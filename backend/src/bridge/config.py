"""Settings (docs/spec/08; REQ-FND-02). Values come from the environment or ``backend/.env``.

Fail closed: a missing or weak secret stops the process at start-up (``get_settings()`` raises), so the app never
runs with a default key. Every variable is documented in ``backend/.env.example``.
"""

from __future__ import annotations

import base64
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIN_SECRET_CHARS = 32

AppEnv = Literal["dev", "test", "staging", "production"]

# Optional settings: an empty value means unset (None).
OPTIONAL_SETTINGS = (
    "database_owner_url",
    "anthropic_api_key",  # ANTHROPIC_API_KEY= (blank, as in .env.example) means no key
    "postmark_server_token",
    "tier2_local_kek",
    "tier2_kms_key_id",
    "provenance_signing_key",
    "provenance_kms_key_id",
    "tsa_fallback_url",
    "tsa_ca_bundle",
    "tsa_fallback_ca_bundle",
    "s3_endpoint_url",
    "s3_access_key_id",
    "s3_secret_access_key",
    "audit_reader_database_url",
)


class ConfigurationError(RuntimeError):
    """A component was asked for whose settings are missing (fail closed at the point of use, never a default)."""


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

    # OAuth sign-in (REQ-AUTH-02, ADR-002; test apps per D-26). A provider is enabled only when both its client id and
    # secret are set; otherwise its routes answer 404 and the web app hides its button (fail closed).
    github_client_id: SecretStr | None = None
    github_client_secret: SecretStr | None = None
    google_client_id: SecretStr | None = None
    google_client_secret: SecretStr | None = None
    # SMS (REQ-PROV-04: D1 phone codes). The fake in dev, test and CI; Africa's Talking once the vendor account exists
    # (gate G1). bridge.integrations.sms.sms_provider_from_settings refuses the fake in production and the vendor in
    # test.
    sms_provider: Literal["fake", "africastalking"] = "fake"
    africastalking_username: str | None = None
    africastalking_api_key: SecretStr | None = None
    africastalking_sender_id: str | None = None

    # Feature flags (docs/spec/10: default false until the legal gate).
    feature_tier2_enabled: bool = False
    feature_deals_enabled: bool = False

    # Tier-2 envelope encryption (bridge.crypto.envelope; ADR-007): each proposal's data key is wrapped by a key
    # encryption key. Dev/test: TIER2_LOCAL_KEK (base64 of 32 bytes). Production: KMS only (TIER2_KMS_KEY_ID). Code
    # that needs the wrapper fails closed when neither is set; no key is ever generated implicitly.
    tier2_local_kek: SecretStr | None = None
    tier2_kms_key_id: str | None = None

    # Provenance signing (bridge.provenance.signing; ADR-003): Ed25519. Dev/test: PROVENANCE_SIGNING_KEY (base64 of
    # the 32-byte raw private key), read by the worker only. Production: KMS only (PROVENANCE_KMS_KEY_ID).
    provenance_signing_key: SecretStr | None = None
    provenance_kms_key_id: str | None = None

    # RFC 3161 timestamping (bridge.provenance.tsa; ADR-003): DigiCert primary, FreeTSA fallback. Tests never call
    # either (tests/egress.py); they run a local openssl test TSA.
    tsa_url: str = "http://timestamp.digicert.com"
    tsa_fallback_url: str | None = "https://freetsa.org/tsr"
    tsa_timeout_seconds: float = 10.0
    # One timestamp attempt, primary and fallback together: a slow or dripping TSA never holds a worker longer.
    tsa_deadline_seconds: float = Field(default=30.0, gt=0)
    # The pinned CA bundle (PEM file) of each TSA: a token must chain to it. Required outside dev and test (the TSA
    # client fails closed at use without it); ops provide DigiCert's and FreeTSA's before staging.
    tsa_ca_bundle: Path | None = None
    tsa_fallback_ca_bundle: Path | None = None

    # Object storage (bridge.storage.objects; ADR-007): AWS S3 in production, SeaweedFS in dev (D-24, S3_ENDPOINT_URL);
    # "memory" is for tests and is refused in staging and production. Credentials may stay unset where the instance
    # role provides them.
    object_store: Literal["s3", "memory"] = "s3"
    s3_endpoint_url: str | None = None
    s3_region: str = "af-south-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_bucket_evidence: str = "evidence"
    s3_bucket_kyc_review: str = "kyc-review"
    s3_bucket_uploads: str = "uploads"

    # The nightly audit.verify_chain job reads every audit chain as audit_reader, a separate login (roles.sql). The job
    # fails closed without it.
    audit_reader_database_url: SecretStr | None = None

    # Config files.
    plans_file: Path = BACKEND_DIR / "config" / "plans.yaml"
    consents_file: Path = BACKEND_DIR / "config" / "consents.yaml"

    # Runtime LLMs (ADR-005; bridge/llm). Dev and test start without a key (the adapter refuses at call time);
    # production refuses to start without one unless LLM_KILL_SWITCH=1. No test and no make check step reaches
    # the provider (AC-SEC-5; D-18: no paid calls).
    anthropic_api_key: SecretStr | None = None
    llm_kill_switch: bool = False  # LLM_KILL_SWITCH=1 refuses every call with LLMKillSwitch
    # Spend across every tenant per UTC day; 0 refuses every call that costs anything (fail closed).
    llm_global_daily_cap_usd: Decimal = Decimal("0")
    llm_models_file: Path = BACKEND_DIR / "ai" / "models.yaml"

    # Embeddings (ADR-005 decision 6). bge-m3 runs on the worker from local weights only (never downloaded by code).
    embedder: Literal["fake", "bge-m3"] = "fake"
    embedder_model_path: Path | None = None

    # Cookie names are fixed (the web app reads the same names). With Secure cookies they carry the __Host- prefix:
    # Secure, Path=/ and no Domain, so a sibling subdomain cannot plant them. Browsers refuse the prefix without
    # Secure, so plain-http setups (COOKIE_SECURE=false) get the bare names.
    @property
    def session_cookie_name(self) -> str:
        return self._cookie("bridge_session")

    @property
    def csrf_cookie_name(self) -> str:
        return self._cookie("bridge_csrf")

    @property
    def signup_cookie_name(self) -> str:
        return self._cookie("bridge_signup")

    @property
    def oauth_cookie_name(self) -> str:
        """The short-lived OAuth flow cookie (state, nonce, PKCE verifier; bridge.auth.oauth)."""
        return self._cookie("bridge_oauth")

    def _cookie(self, name: str) -> str:
        return f"__Host-{name}" if self.cookie_secure else name

    @field_validator(*OPTIONAL_SETTINGS, mode="before")
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        """``NAME=`` (an empty value, as in ``.env.example`` or a compose override) means unset, never an empty key,
        URL or path: the component that needs it then fails closed at use."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

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
        if self.llm_global_daily_cap_usd < 0:
            problems.append("LLM_GLOBAL_DAILY_CAP_USD must be zero or more")
        for provider in ("github", "google"):
            pair = [getattr(self, f"{provider}_client_{part}") for part in ("id", "secret")]
            if len({_is_set(value) for value in pair}) == 2:
                # Half a configuration is a mistake, not a choice: refuse to start rather than guess.
                name = provider.upper()
                problems.append(f"{name}_CLIENT_ID and {name}_CLIENT_SECRET must be set together (or both left empty)")
        if self.sms_provider == "africastalking" and (
            not self.africastalking_username or not self.africastalking_api_key
        ):
            problems.append(
                "AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY are required when SMS_PROVIDER=africastalking"
            )
        problems.extend(self._key_problems())
        if self.app_env == "production":
            if self.embedder == "fake":
                problems.append("production embeds with a real model only (EMBEDDER=bge-m3)")
            if self.anthropic_api_key is None and not self.llm_kill_switch:
                problems.append("ANTHROPIC_API_KEY is required in production unless LLM_KILL_SWITCH=1")
            if self.email_provider != "postmark":
                problems.append("production sends email through Postmark only (EMAIL_PROVIDER=postmark)")
            if not self.public_base_url.startswith("https://"):
                problems.append("PUBLIC_BASE_URL must be https in production")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def _key_problems(self) -> list[str]:
        """Tier-2 and provenance key settings: well-formed when set, one source each, KMS only in production."""
        problems: list[str] = []
        pairs = (
            ("TIER2_LOCAL_KEK", self.tier2_local_kek, "TIER2_KMS_KEY_ID", self.tier2_kms_key_id),
            (
                "PROVENANCE_SIGNING_KEY",
                self.provenance_signing_key,
                "PROVENANCE_KMS_KEY_ID",
                self.provenance_kms_key_id,
            ),
        )
        for local_name, local, kms_name, kms in pairs:
            if local is None:
                continue
            if decoded_key(local) is None:
                problems.append(f"{local_name} must be base64 of exactly 32 bytes")
            if kms:
                problems.append(f"set {local_name} or {kms_name}, not both")
            if self.app_env == "production":
                problems.append(f"{local_name} is for dev and test; production uses KMS ({kms_name})")
        if self.object_store == "memory" and self.app_env in ("staging", "production"):
            problems.append("OBJECT_STORE=memory is for tests; staging and production use s3")
        return problems


def decoded_key(value: SecretStr) -> bytes | None:
    """The 32 raw bytes of a base64 key setting, or None when it is not base64 of exactly 32 bytes."""
    try:
        raw = base64.b64decode(value.get_secret_value(), validate=True)
    except ValueError:
        return None
    return raw if len(raw) == 32 else None


def _is_set(value: SecretStr | None) -> bool:
    return value is not None and bool(value.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings; raises (fails closed) when a required value is missing or weak."""
    return Settings()  # values come from the environment
