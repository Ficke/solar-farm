"""Authenticate plug and scheduler calls to the public edge service.

IAP handles dashboard authentication before requests reach solar-web.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import HTTPException, Request

TokenVerifier = Callable[[str, str], dict]


def google_verifier(token: str, audience: str) -> dict:
    from google.auth.transport import requests as gat
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, gat.Request(), audience=audience)


def check_plug_key(given: str | None, expected: str) -> None:
    if not expected or not given or not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="bad plug key")


def check_scheduler(request: Request, expected_email: str, verify: TokenVerifier) -> None:
    """Cloud Scheduler sends a Google-signed ID token whose audience is our URL."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or not expected_email:
        raise HTTPException(status_code=401, detail="missing token")
    audience = f"https://{request.url.hostname}"
    try:
        claims = verify(header.removeprefix("Bearer "), audience)
    except Exception as e:
        raise HTTPException(status_code=401, detail="invalid token") from e
    if claims.get("email") != expected_email or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="not the scheduler")
