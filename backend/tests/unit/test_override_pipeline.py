"""Pipeline-Wirkung der Per-User-Modi-Overrides (voll editierbar).

Merge-Präzedenz + Local-Grenze: gewählte STT/LLM greifen online, werden in
local **still** von den lokalen Providern überstimmt (kein Fehler); der
Per-Request-Override bleibt in local hart (400). STT-Wahl leert den
Cloud-Fallback. apply_llm-Tri-State schaltet die Nachbearbeitung an/aus; ein
fehlkonfiguriertes apply_llm=an → 409. enabled=false → 403. DELETE → Default.
"""

from __future__ import annotations

from sqlmodel import Session, select

from sprichblitz_backend.db.models import User
from sprichblitz_backend.services import mode_overrides


def _uid(engine) -> int:
    with Session(engine) as s:
        return s.exec(select(User).where(User.name == "tester")).first().id


def _set_location(engine, location: str) -> None:
    with Session(engine) as s:
        user = s.exec(select(User).where(User.name == "tester")).first()
        user.processing_location = location
        s.add(user)
        s.commit()


def _override(engine, mode_key: str, **fields) -> None:
    with Session(engine) as s:
        mode_overrides.upsert_override(s, _uid(engine), mode_key, **fields)


def _post(client, headers, mode, wav, **data):
    return client.post(
        "/full",
        headers=headers,
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"mode": mode, **data},
    )


def test_override_prompt_and_preferred_llm_apply_online(
    client, db_engine, stub_registry, auth_headers, make_wav_bytes
) -> None:
    _override(
        db_engine,
        "mail",
        display_name="Mail X",
        system_prompt="CUSTOM PROMPT",
        llm_provider="lm_studio",
        enabled=True,
    )
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200, res.text
    assert res.json()["llm_provider"] == "lm_studio"  # gewähltes LLM wirkt online
    assert "CUSTOM PROMPT" in stub_registry.llm["lm_studio"].calls[-1]["system"]


def test_stt_override_applies_online(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    # exact_de nutzt per Default Cloud-Whisper; Override auf den lokalen STT wirkt online.
    _override(db_engine, "exact_de", stt_provider="lm_studio_whisper", enabled=True)
    res = _post(client, auth_headers, "exact_de", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200, res.text
    assert res.json()["stt_provider"] == "lm_studio_whisper"


def test_stt_override_clears_fallback(
    client, db_engine, stub_registry, auth_headers, make_wav_bytes
) -> None:
    # exact_swiss hat fallback_stt=openai_whisper. Wählt der Nutzer die STT bewusst,
    # wird der Cloud-Fallback geleert: schlägt der primäre STT fehl, KEIN stiller Cloud-Call.
    async def _boom(*a, **k):
        from sprichblitz_backend.util.errors import ProviderUnavailable

        raise ProviderUnavailable("down", provider="lm_studio_whisper")

    stub_registry.stt["lm_studio_whisper"].transcribe = _boom
    _override(db_engine, "exact_swiss", stt_provider="lm_studio_whisper", enabled=True)
    res = _post(client, auth_headers, "exact_swiss", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 503  # kein Fallback auf Cloud-Whisper
    assert stub_registry.stt["openai_whisper"].calls == []


def test_preferred_online_llm_silently_ignored_in_local(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    _set_location(db_engine, "local")
    _override(
        db_engine,
        "mail",
        display_name=None,
        system_prompt=None,
        llm_provider="anthropic",  # Cloud-Präferenz
        stt_provider="openai_whisper",  # Cloud-STT-Präferenz
        enabled=True,
    )
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200  # KEIN Fehler
    body = res.json()
    assert body["stt_provider"] == "lm_studio_whisper"  # lokal, Cloud-STT still ignoriert
    assert body["llm_provider"] == "lm_studio"  # Qwen lokal, preferred ignoriert


def test_apply_llm_override_off_skips_llm(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    # mail hat apply_llm=true; Override auf Aus liefert den rohen STT-Text ohne LLM.
    _override(db_engine, "mail", apply_llm=False, enabled=True)
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["llm_provider"] is None
    assert body["final_text"] == body["raw_text"]


def test_apply_llm_override_on_enables_llm(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    # exact_de hat apply_llm=false; Override an + Prompt + LLM aktiviert die Nachbearbeitung.
    _override(
        db_engine,
        "exact_de",
        apply_llm=True,
        system_prompt="POLISH",
        llm_provider="anthropic",
        enabled=True,
    )
    res = _post(client, auth_headers, "exact_de", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200, res.text
    assert res.json()["llm_provider"] == "anthropic"


def test_apply_llm_on_without_prompt_is_misconfigured(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    # Defensiv (409): ein direkt gespeicherter Override mit apply_llm an, aber ohne
    # effektiven Prompt (exact_de hat keinen Default-Prompt) darf kein 500 werden.
    _override(db_engine, "exact_de", apply_llm=True, llm_provider="anthropic", enabled=True)
    res = _post(client, auth_headers, "exact_de", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 409
    assert res.json()["code"] == "mode_misconfigured"


def test_per_request_cloud_override_still_hard_in_local(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    _set_location(db_engine, "local")
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0), llm="anthropic")
    assert res.status_code == 400
    assert res.json()["code"] == "override_not_allowed"


def test_disabled_mode_returns_403(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    _override(
        db_engine,
        "mail",
        display_name=None,
        system_prompt=None,
        llm_provider=None,
        enabled=False,
    )
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 403
    assert res.json()["code"] == "mode_disabled"


def test_delete_override_resets_to_default(
    client, db_engine, auth_headers, make_wav_bytes
) -> None:
    _override(
        db_engine,
        "mail",
        display_name=None,
        system_prompt="X",
        llm_provider="lm_studio",
        enabled=True,
    )
    with Session(db_engine) as s:
        mode_overrides.delete_override(s, _uid(db_engine), "mail")
    res = _post(client, auth_headers, "mail", make_wav_bytes(16_000, 2.0))
    assert res.status_code == 200
    assert res.json()["llm_provider"] == "anthropic"  # zurück auf Backend-Default
