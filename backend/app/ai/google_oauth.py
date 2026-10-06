"""Google OAuth 2.0 (authorization-code flow) for a web app.

Flow, end to end:

    1. Frontend (authenticated) asks the backend for a consent URL.
    2. Backend builds it, embedding a *signed* `state` that carries the app
       user's id so the callback can attribute the returned token. State is a
       short-lived JWT signed with the app SECRET_KEY, so it cannot be forged.
    3. The user consents on Google's screen and Google redirects the browser to
       the backend callback with `code` + `state`.
    4. Backend verifies `state`, exchanges `code` for tokens, stores them, and
       redirects the browser back to the frontend.

The token exchange happens server-side; the browser never sees the refresh
token. All Google libraries are imported lazily so the rest of the app runs
without them installed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from .. import models
from ..config import settings

STATE_TTL_SECONDS = 600
_STATE_ALG = "HS256"

# oauthlib refuses to exchange a code over a plain-http callback. On localhost
# (http://127.0.0.1 / http://localhost) that is the normal dev setup, so opt in
# to insecure transport. In production the redirect URI is https and this stays
# off, keeping the safety check active.
if settings.GOOGLE_REDIRECT_URI.lower().startswith("http://"):
    host = settings.GOOGLE_REDIRECT_URI.lower()
    if "127.0.0.1" in host or "localhost" in host:
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
        # google-auth also honours relaxing the scope-changed check, which
        # Google sometimes triggers by adding 'openid'.
        os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class OAuthError(RuntimeError):
    pass


def _require_libs() -> None:
    try:
        import google_auth_oauthlib.flow  # noqa: F401
        import google.oauth2.credentials  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise OAuthError(
            "Google OAuth libraries are not installed. Run: pip install "
            "google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from exc


def _client_config() -> dict[str, Any]:
    """Build the client config google-auth expects, from env or JSON file."""
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        return {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        }

    path = settings.GOOGLE_CLIENT_SECRET_FILE
    if not os.path.exists(path):
        raise OAuthError(
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET, or place client_secret.json at "
            f"{path}. See docs/GOOGLE_MEET_API.md."
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # A downloaded client secret is nested under "web" or "installed".
    if "web" not in data and "installed" in data:
        data = {"web": data["installed"]}
    return data


def _build_flow(state: str | None = None, code_verifier: str | None = None):
    _require_libs()
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        _client_config(),
        scopes=settings.GOOGLE_SCOPES,
        state=state,
        # We manage the PKCE code_verifier ourselves so it survives the round
        # trip between the authorize and callback requests (see below).
        autogenerate_code_verifier=False,
    )
    if code_verifier is not None:
        flow.code_verifier = code_verifier
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


# ─────────────────────────────── state ───────────────────────────────────

def _new_code_verifier() -> str:
    # PKCE verifier: 43-128 chars from the unreserved set. token_urlsafe(64)
    # yields ~86 URL-safe chars, comfortably inside the spec.
    import secrets

    return secrets.token_urlsafe(64)


def _make_state(user_id: int, code_verifier: str) -> str:
    payload = {
        "uid": user_id,
        "purpose": "google_oauth",
        # Carry the PKCE verifier in the signed state so the stateless callback
        # can reconstruct it. The state is signed with SECRET_KEY, so the
        # verifier cannot be read or forged by anyone else.
        "cv": code_verifier,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=STATE_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_STATE_ALG)


def _read_state(state: str) -> tuple[int, str | None]:
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[_STATE_ALG])
    except JWTError as exc:
        raise OAuthError("The OAuth state is invalid or has expired.") from exc
    if payload.get("purpose") != "google_oauth" or "uid" not in payload:
        raise OAuthError("The OAuth state is malformed.")
    return int(payload["uid"]), payload.get("cv")


# The scope required to create calendar events and email guests. Its readonly
# sibling is NOT sufficient — inserts return 403 insufficientPermissions.
CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


# ───────────────────────────── public API ────────────────────────────────

def authorization_url(user_id: int) -> str:
    """Consent URL to send the user's browser to."""
    code_verifier = _new_code_verifier()
    flow = _build_flow(state=_make_state(user_id, code_verifier), code_verifier=code_verifier)
    url, _ = flow.authorization_url(
        access_type="offline",  # ask for a refresh token
        include_granted_scopes="true",
        prompt="consent",  # force a refresh token even on re-consent
    )
    return url


def handle_callback(db: Session, full_callback_url: str, state: str) -> models.GoogleCredential:
    """Exchange the authorization code and persist the user's tokens."""
    user_id, code_verifier = _read_state(state)

    flow = _build_flow(state=state, code_verifier=code_verifier)
    # google-auth reads the code (and validates state) from the full URL.
    flow.fetch_token(authorization_response=_force_https_for_localhost(full_callback_url))
    creds = flow.credentials

    email = _fetch_email(creds)
    return _store(db, user_id, creds, email)


def _force_https_for_localhost(url: str) -> str:
    # oauthlib refuses http:// callbacks unless told the transport is insecure.
    # For a real deployment the redirect URI is https and this is a no-op.
    return url


def _fetch_email(creds) -> str | None:
    try:
        from googleapiclient.discovery import build

        service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
        info = service.userinfo().get().execute()
        return info.get("email")
    except Exception:
        return None


def _store(db: Session, user_id: int, creds, email: str | None) -> models.GoogleCredential:
    row = (
        db.query(models.GoogleCredential)
        .filter(models.GoogleCredential.user_id == user_id)
        .first()
    )
    if row is None:
        row = models.GoogleCredential(user_id=user_id)
        db.add(row)

    row.token = creds.token
    # Google only returns a refresh token on first consent; keep the old one
    # if this exchange did not include a new one.
    if getattr(creds, "refresh_token", None):
        row.refresh_token = creds.refresh_token
    row.token_uri = creds.token_uri
    row.client_id = creds.client_id
    row.client_secret = creds.client_secret
    row.scopes = " ".join(creds.scopes or settings.GOOGLE_SCOPES)
    row.expiry = getattr(creds, "expiry", None)
    row.google_email = email or row.google_email
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def load_credentials(db: Session, user_id: int):
    """Rebuild a google Credentials object for a user, refreshing if needed.

    Returns None when the user has not connected Google.
    """
    _require_libs()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    row = (
        db.query(models.GoogleCredential)
        .filter(models.GoogleCredential.user_id == user_id)
        .first()
    )
    if row is None or not row.refresh_token:
        return None

    if row.client_id and settings.GOOGLE_CLIENT_ID and row.client_id != settings.GOOGLE_CLIENT_ID:
        # The stored credentials belong to a different (or deleted) OAuth client. Purge them.
        db.delete(row)
        db.commit()
        return None

    creds = Credentials(
        token=row.token,
        refresh_token=row.refresh_token,
        token_uri=row.token_uri or "https://oauth2.googleapis.com/token",
        client_id=row.client_id or settings.GOOGLE_CLIENT_ID,
        client_secret=row.client_secret or settings.GOOGLE_CLIENT_SECRET,
        scopes=(row.scopes or "").split() or settings.GOOGLE_SCOPES,
    )

    if not creds.valid:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise OAuthError(
                f"Your Google connection could not be refreshed ({exc}). "
                "Please reconnect your account."
            ) from exc
        # Persist the refreshed access token.
        row.token = creds.token
        row.expiry = getattr(creds, "expiry", None)
        row.updated_at = datetime.utcnow()
        db.commit()

    return creds


def connection_status(db: Session, user_id: int) -> dict[str, Any]:
    row = (
        db.query(models.GoogleCredential)
        .filter(models.GoogleCredential.user_id == user_id)
        .first()
    )
    if row and row.client_id and settings.GOOGLE_CLIENT_ID and row.client_id != settings.GOOGLE_CLIENT_ID:
        db.delete(row)
        db.commit()
        row = None

    granted = row.scopes.split() if row and row.scopes else []
    return {
        "configured": settings.google_configured,
        "connected": bool(row and row.refresh_token),
        "email": row.google_email if row else None,
        "scopes": granted,
        # A token minted before calendar.events was requested carries only the
        # readonly scope, so writes fail with 403 "insufficient authentication
        # scopes". Surface that up front instead of at scheduling time.
        "can_write_calendar": CALENDAR_WRITE_SCOPE in granted,
        "needs_reconnect": bool(row and row.refresh_token)
        and CALENDAR_WRITE_SCOPE not in granted,
    }


def disconnect(db: Session, user_id: int) -> None:
    row = (
        db.query(models.GoogleCredential)
        .filter(models.GoogleCredential.user_id == user_id)
        .first()
    )
    if not row:
        return
    # Best-effort revoke at Google, then delete locally.
    try:
        import requests

        if row.token:
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": row.token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
    except Exception:
        pass
    db.delete(row)
    db.commit()
