from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.domain import CompletionResult, TranscriptionResult


class STTProvider(ABC):
    """Abstract base for speech-to-text providers."""

    name: str
    model: str
    # Welcher BYO-Key gilt (None = lokal/kein Key). Von der Registry gesetzt;
    # steuert in Etappe 5, ob der Call durchs LocalInferenceGate läuft.
    key_provider: str | None = None

    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        language: str = "de",
        prompt_hint: str | None = None,
        api_key: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe ``audio`` (16 kHz mono PCM in WAV container) to text.

        ``api_key`` (when given) is the per-request Per-User key; ``None`` falls
        back to the provider's configured env key (legacy/local path).
        """

    @abstractmethod
    async def health_check(self, api_key: str | None = None) -> bool:
        """Return True if the underlying provider responds within a short timeout.

        ``api_key`` (when given) is the per-user BYO key: the /config health
        probe passes it so a key-requiring cloud provider can be tested with the
        caller's actual key instead of showing „offline" for a keyless probe.
        """


class LLMProvider(ABC):
    """Abstract base for chat/completion providers."""

    name: str
    default_model: str
    key_provider: str | None = None  # None = lokal/kein Key (siehe STTProvider)

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 1000,
        prefill: str | None = None,
        api_key: str | None = None,
    ) -> CompletionResult:
        """Run a chat-style completion.

        ``model`` defaults to ``self.default_model`` when None.
        ``prefill`` is honoured by providers that support assistant prefill
        (currently only Anthropic). Other providers may ignore it.
        """

    @abstractmethod
    async def list_models(self, api_key: str | None = None) -> list[str]:
        """Return all model identifiers the provider exposes.

        On error, return an empty list rather than raising. ``api_key`` (when
        given) is the per-user BYO key so /config can populate the model
        dropdown for key-requiring cloud providers instead of returning [].
        """

    @abstractmethod
    async def health_check(self, api_key: str | None = None) -> bool:
        """Return True if the underlying provider responds within a short timeout.

        See :meth:`STTProvider.health_check` for the ``api_key`` semantics.
        """
