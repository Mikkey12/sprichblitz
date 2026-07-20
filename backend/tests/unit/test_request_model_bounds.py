"""Requestmodelle lehnen unbekannte und unbeschränkt grosse Felder früh ab."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sprichblitz_backend.models.api import ProcessRequest
from sprichblitz_backend.routes.admin import CreateUserRequest, ModeWriteRequest
from sprichblitz_backend.routes.me import SetKeyRequest


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ProcessRequest, {"mode": "exact_de", "text": "ok", "ignored": "x"}),
        (SetKeyRequest, {"key": "secret", "ignored": "x"}),
        (CreateUserRequest, {"name": "user", "ignored": "x"}),
    ],
)
def test_request_models_forbid_unknown_fields(model, payload) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(payload)


def test_key_and_global_mode_text_fields_are_bounded() -> None:
    with pytest.raises(ValidationError):
        SetKeyRequest(key="x" * 16_385)
    with pytest.raises(ValidationError):
        ModeWriteRequest(system_prompt="x" * 4001)
