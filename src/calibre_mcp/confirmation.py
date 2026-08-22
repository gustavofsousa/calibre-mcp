"""Plan->confirm intent gate (AD-012, EDIT-01/03, REM-01/05).

Turns edit/remove into a reviewed two-step handshake. ``plan_token`` derives a
deterministic token from the exact operation params, so the apply call can
recompute it and prove that what is being applied is exactly what was planned.
The token is not a secret — it is an integrity check that the applied op equals
the reviewed op.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .errors import ConfirmationError

_TOKEN_LENGTH = 16


def plan_token(op: str, book_id: int, payload: dict[str, Any]) -> str:
    """Return a deterministic token for ``op|book_id|payload``.

    The payload is normalized with JSON sorted keys so logically-equal payloads
    (any key order) always produce the same token.
    """
    normalized = f"{op}|{book_id}|{json.dumps(payload, sort_keys=True)}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:_TOKEN_LENGTH]


def verify(op: str, book_id: int, payload: dict[str, Any], token: str) -> None:
    """Raise ``ConfirmationError`` when ``token`` does not match the recomputed
    plan token for this exact operation (EDIT-03, REM-05)."""
    expected = plan_token(op, book_id, payload)
    if not hmac.compare_digest(expected, token):
        raise ConfirmationError(
            "confirmation token does not match the requested change; re-plan "
            "and review before applying"
        )
