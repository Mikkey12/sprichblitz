from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Modi sind vollständig config-getrieben (config.yml → cfg.modes). Es gibt KEIN
# festes Enum-Gate mehr: ``mode`` ist überall ein ``str`` und wird gegen die
# geladene Config validiert (ModeNotConfigured). ``Mode`` bleibt als Alias
# bestehen, damit bestehende Importe/Annotationen ``mode: Mode`` weiter tragen –
# er ist jetzt schlicht ``str``.
Mode = str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    uptime_seconds: int


class ModeInfo(BaseModel):
    name: Mode
    description: str
    stt_provider: str
    llm_provider: str | None = None
    apply_llm: bool
    # Etappe 4 (additiv – Alt-Client parst description/llm_provider weiter):
    # display_name = effektive, override-bewusste Bezeichnung (Override ← Default);
    # preferred_online_llm = ONLINE-Präferenz (NICHT der location-aufgelöste Provider).
    display_name: str | None = None
    enabled: bool = True
    preferred_online_llm: str | None = None


class ProviderInfo(BaseModel):
    name: str
    type: str
    healthy: bool
    default_model: str
    available_models: list[str] = Field(default_factory=list)
    # True = lokaler Provider ohne Cloud-Key (key_provider is None) – dieselbe
    # Grenze, die das LocalInferenceGate und der BYO-Key-Resolver nutzen. Speist
    # das „lokal/online"-Badge im Konsolen-Modi-Editor.
    local: bool = False


class ConfigResponse(BaseModel):
    version: str
    modes: list[ModeInfo]
    stt_providers: list[ProviderInfo]
    llm_providers: list[ProviderInfo]


class TranscribeResponse(BaseModel):
    mode: Mode
    text: str
    stt_provider: str
    stt_model: str
    used_fallback: bool = False
    duration_ms: int
    audio_seconds: float


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode = Field(min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=20_000)
    # Optionale Per-Request-Overrides (Stufe A). Leer/None = Backend-Config.
    llm: str | None = Field(default=None, max_length=64)
    llm_model: str | None = Field(default=None, max_length=200)
    # Locale-Hint (z. B. de-CH); steuert die deterministische
    # Orthografie-Korrektur (ß→ss bei *-CH) und einen LLM-Prompt-Bonus.
    locale: str | None = Field(default=None, min_length=2, max_length=35)


class ProcessResponse(BaseModel):
    mode: Mode
    text: str
    llm_provider: str
    llm_model: str
    duration_ms: int


class FullResponse(BaseModel):
    mode: Mode
    raw_text: str
    final_text: str
    stt_provider: str
    stt_model: str
    llm_provider: str | None = None
    llm_model: str | None = None
    used_fallback: bool = False
    audio_seconds: float = 0.0  # Etappe 5 (additiv): Audio-Dauer fürs Usage-Booking
    total_duration_ms: int


class ModeStats(BaseModel):
    requests: int = 0
    errors: int = 0
    total_audio_seconds: float = 0.0


class StatsResponse(BaseModel):
    per_mode: dict[Mode, ModeStats]


class ErrorResponse(BaseModel):
    error: str
    code: str
    provider: str | None = None
