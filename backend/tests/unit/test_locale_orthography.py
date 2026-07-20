from __future__ import annotations

import pytest

from sprichblitz_backend.services.locale_orthography import (
    apply_locale_orthography,
    llm_system_prompt_for_locale,
    swiss_orthography_hint,
)


@pytest.mark.parametrize("locale", ["de-CH", "fr-CH", "it-CH", "DE-ch", "de-ch"])
def test_swiss_locales_replace_eszett(locale: str) -> None:
    assert apply_locale_orthography("Straße weiß groß", locale) == "Strasse weiss gross"


def test_capital_eszett_replaced() -> None:
    assert apply_locale_orthography("STRAẞE", "de-CH") == "STRASSE"


@pytest.mark.parametrize("locale", ["de-DE", "de-AT", "en-US", "fr-FR", None, ""])
def test_non_swiss_locales_leave_text_unchanged(locale: str | None) -> None:
    assert apply_locale_orthography("Straße weiß groß", locale) == "Straße weiß groß"


def test_empty_text_is_noop() -> None:
    assert apply_locale_orthography("", "de-CH") == ""


def test_idempotent() -> None:
    text = "Straße weiß"
    once = apply_locale_orthography(text, "de-CH")
    twice = apply_locale_orthography(once, "de-CH")
    assert once == twice == "Strasse weiss"


def test_llm_hint_only_for_swiss() -> None:
    base = "Du bist ein Sprach-Veredler."
    assert llm_system_prompt_for_locale(base, None) == base
    assert llm_system_prompt_for_locale(base, "de-DE") == base
    out = llm_system_prompt_for_locale(base, "de-CH")
    assert out.startswith(base)
    assert "Schweizer Standarddeutsch" in out
    assert "ss" in out
    assert swiss_orthography_hint() in out
