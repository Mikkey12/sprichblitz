from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .domain import ByoProvider


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="0.0.0.0", min_length=1, max_length=255)
    port: int = Field(default=8000, ge=1, le=65_535)
    # Interaktive OpenAPI-Doku (/docs) + Schema (/openapi.json). Default AUS:
    # öffentlich erreichbar legt sie die gesamte API-Struktur offen (Recon) und
    # Swagger-UI lädt Assets von einem CDN. Für die lokale Entwicklung per
    # `server.docs: true` einschalten.
    docs: bool = False


class STTProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    base_url: str
    # Optionaler, absoluter Pfad auf demselben Origin für Provider ohne
    # /v1/models (z. B. WhisperKit: /health). None = /models verwenden.
    health_path: str | None = Field(default=None, max_length=255)
    api_key_env: str = ""
    model: str
    # Welcher BYO-Per-User-Key gilt für diesen Provider? None = lokal (kein Key).
    # Pydantic validiert gegen ByoProvider → Tippfehler in config.yml = Abbruch.
    key_provider: ByoProvider | None = None

    @field_validator("health_path")
    @classmethod
    def _absolute_health_path(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/")
            or value.startswith("//")
            or "://" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("health_path muss ein absoluter URL-Pfad ohne Query/Fragment sein")
        return value


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    base_url: str | None = None
    health_path: str | None = Field(default=None, max_length=255)
    api_key_env: str = ""
    default_model: str
    # Siehe STTProviderConfig.key_provider.
    key_provider: ByoProvider | None = None

    @field_validator("health_path")
    @classmethod
    def _absolute_health_path(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.startswith("/")
            or value.startswith("//")
            or "://" in value
            or "?" in value
            or "#" in value
        ):
            raise ValueError("health_path muss ein absoluter URL-Pfad ohne Query/Fragment sein")
        return value


class ModeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    stt: str
    language: str = "de"
    prompt_hint: str | None = None
    apply_llm: bool = False
    llm: str | None = None
    llm_model: str | None = None
    output_prefill: str = ""
    system_prompt: str | None = None
    fallback_stt: str | None = None


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None → absolut verankerter Default aus db.engine (honoriert SPRICHBLITZ_DB_URL).
    url: str | None = None


class LocalProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Provider für processing_location=local (§6): WhisperKit-STT + LM-Studio-Qwen-LLM.
    # Gelten für ALLE Modi (beide Stufen); online nutzt weiter die per-Mode-Provider.
    stt: str = "lm_studio_whisper"
    llm: str = "lm_studio"


class LimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Nebenläufigkeit & Limits (Etappe 5); Defaults bewusst großzügig.
    local_concurrency: int = Field(default=1, ge=1, le=32)
    local_acquire_timeout_s: float = Field(default=30.0, gt=0, le=300)
    rate_limit_capacity: int = Field(default=60, ge=1, le=10_000)  # Burst pro Nutzer
    # 0 ist ein bewusst zulässiger Test-/Lockdown-Modus: Bucket füllt nie nach.
    rate_limit_refill_per_min: float = Field(default=120.0, ge=0, le=100_000)


class CfAccessConfig(BaseModel):
    """Cloudflare-Access-Parameter (nur relevant bei auth.mode=token_plus_cf_access)."""

    model_config = ConfigDict(extra="forbid")

    # Reiner Teamname (z. B. "myteam") – iss/JWKS werden daraus abgeleitet.
    team_domain: str = Field(default="", max_length=63)
    # AUD-Tag der Access-Application (der am häufigsten vergessene Check).
    application_aud: str = Field(default="", max_length=512)
    # Rohe TCP-Peers, die als Tunnel-Ingress (cloudflared) gelten dürfen.
    trusted_proxy_ips: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "::1"], min_length=1, max_length=64
    )
    jwks_cache_ttl_s: float = Field(default=3600.0, gt=0, le=86_400)
    # Negativ-Cache: höchstens 1 JWKS-Refetch pro Intervall (unknown-kid-Flut bremsen).
    jwks_min_refetch_interval_s: float = Field(default=60.0, ge=0, le=3600)

    @field_validator("team_domain")
    @classmethod
    def _bare_team_slug(cls, v: str) -> str:
        if v and ("://" in v or "/" in v or "." in v):
            raise ValueError(
                "team_domain muss der reine Teamname sein (kein https://, kein Host), z. B. 'myteam'"
            )
        return v


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["token_only", "token_plus_cf_access"] = "token_only"
    cf_access: CfAccessConfig = Field(default_factory=CfAccessConfig)
    # Console-Bootstrap gegen Session-Fixation: verlangt einen Client-Nonce
    # (Cookie ``sb_boot`` == an den Code gebundener Nonce). Default False =
    # rückwärtskompatibel (Codes MIT Nonce werden trotzdem geprüft; ohne Nonce
    # gilt das Alt-Verhalten). Auf True stellen, sobald ALLE Clients den Nonce
    # setzen – dann werden nonce-lose Codes abgelehnt (Fixation ganz zu).
    require_console_nonce: bool = False

    @model_validator(mode="after")
    def _cf_fields_required_in_cf_mode(self) -> AuthConfig:
        # Fail-closed: cf-Modus ohne team_domain/aud startet nicht (analog SECRET_KEY).
        if self.mode == "token_plus_cf_access" and (
            not self.cf_access.team_domain or not self.cf_access.application_aud
        ):
            raise ValueError(
                "auth.mode=token_plus_cf_access verlangt cf_access.team_domain und application_aud"
            )
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    local_providers: LocalProvidersConfig = Field(default_factory=LocalProvidersConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    stt_providers: dict[str, STTProviderConfig] = Field(default_factory=dict)
    llm_providers: dict[str, LLMProviderConfig] = Field(default_factory=dict)
    modes: dict[str, ModeConfig] = Field(default_factory=dict)
