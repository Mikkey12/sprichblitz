from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ByoProvider(StrEnum):
    """Cloud-Provider, für die Nutzer eigene API-Keys hinterlegen (BYO)."""

    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    openrouter = "openrouter"


class TranscriptionResult(BaseModel):
    text: str
    language: str
    confidence: float | None = None
    provider: str
    model: str


class CompletionResult(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
