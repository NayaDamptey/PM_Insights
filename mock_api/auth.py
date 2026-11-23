"""Authorization header checks, one per vendor scheme.

Clients send exactly the headers the live services expect, so the same client code
works against the mock and the real APIs; only the base URL and secrets change.
"""

from __future__ import annotations

import base64
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBearer

# These scheme objects only describe the auth to OpenAPI, which gives /docs its
# "Authorize" button. auto_error=False leaves the actual checking to the functions
# below, so the 401 responses stay in each vendor's format.
_mri_docs = HTTPBasic(scheme_name="MRI (Qube, API Services)", auto_error=False)
_fixflo_docs = HTTPBearer(scheme_name="FixFlo", auto_error=False)
_engage_docs = HTTPBearer(scheme_name="Engage", auto_error=False)


def _settings(request: Request):  # noqa: ANN202 - avoids a circular import
    return request.app.state.settings


def require_mri_basic(request: Request, _: object = Depends(_mri_docs)) -> None:
    """MRI: ``Authorization: Basic base64("ClientID/Database/User/PartnerKey:Password")``."""
    s = _settings(request)
    expected_user = f"{s.mri_client_id}/{s.mri_database}/{s.mri_user}/{s.mri_partner_key}"
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    ok = False
    if scheme.lower() == "basic" and token:
        try:
            user, _, password = base64.b64decode(token).decode("utf-8").partition(":")
        except (ValueError, UnicodeDecodeError):
            user, password = "", ""
        ok = secrets.compare_digest(user, expected_user) and secrets.compare_digest(
            password, s.mri_password
        )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials or partner key",
            headers={"WWW-Authenticate": 'Basic realm="MRIAPIServices"'},
        )


def _require_bearer(request: Request, expected: str, realm: str) -> None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Authorization has been denied for this request.",
            headers={"WWW-Authenticate": f'Bearer realm="{realm}"'},
        )


def require_fixflo_bearer(request: Request, _: object = Depends(_fixflo_docs)) -> None:
    _require_bearer(request, _settings(request).fixflo_token, "FixFlo")


def require_engage_bearer(request: Request, _: object = Depends(_engage_docs)) -> None:
    _require_bearer(request, _settings(request).engage_token, "Engage")
