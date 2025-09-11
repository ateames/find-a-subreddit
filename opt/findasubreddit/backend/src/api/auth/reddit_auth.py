# backend/src/api/auth/reddit_auth.py
import os
import jwt
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse

import asyncpraw

# --- Catch the right exceptions (asyncprawcore). Fallback to prawcore if needed. ---
try:
    from asyncprawcore.exceptions import (
        OAuthException as CoreOAuthException,
        ResponseException as CoreResponseException,
        PrawcoreException as CorePrawcoreException,
    )
except Exception:  # pragma: no cover
    from prawcore.exceptions import (  # type: ignore
        OAuthException as CoreOAuthException,
        ResponseException as CoreResponseException,
        PrawcoreException as CorePrawcoreException,
    )

logger = logging.getLogger("reddit_auth")

# === Config ===
JWT_SECRET = os.getenv("JWT_SECRET", "supersecret123")  # TODO: set in prod
JWT_ALGORITHM = "HS256"
JWT_EXP_DELTA_SECONDS = 3600

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_REDIRECT_URI = os.getenv("REDDIT_REDIRECT_URI")  # e.g. https://api.YOUR_DOMAIN/api/auth/reddit/callback
REDDIT_SCOPE = "identity submit read flair mysubreddits history"
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "ai-reddit-prototype/0.1")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN")  # e.g. https://YOUR_DOMAIN

# Cookie settings
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # 'lax' or 'none'
# For cross-domain cookies between api.YOUR_DOMAIN and YOUR_DOMAIN
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN")  # e.g. ".YOUR_DOMAIN" or None for host-only
OAUTH_STATE_COOKIE = "oauth_state"
TOKEN_COOKIE = "reddit_token"

router = APIRouter()  # NOTE: no prefix here; we add it when including


@router.get("/debug")
async def auth_debug():
    """Debug endpoint to verify env/config at runtime (no secrets leaked)."""
    return {
        "reddit_client_id_exists": bool(REDDIT_CLIENT_ID),
        "reddit_client_secret_exists": bool(REDDIT_CLIENT_SECRET),
        "reddit_redirect_uri": REDDIT_REDIRECT_URI or "NOT_SET",
        "frontend_origin": FRONTEND_ORIGIN or "NOT_SET",
        "cookie_secure": COOKIE_SECURE,
        "cookie_samesite": COOKIE_SAMESITE,
        "cookie_domain": COOKIE_DOMAIN or "HOST_ONLY",
        "jwt_secret_exists": bool(JWT_SECRET),
        "reddit_user_agent": REDDIT_USER_AGENT,
        "status": "OK"
        if (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and REDDIT_REDIRECT_URI and FRONTEND_ORIGIN)
        else "MISSING_ENV_VARS",
    }


def create_jwt(payload: dict) -> str:
    """Create a short-lived JWT that holds the Reddit refresh token + identity basics."""
    claims = dict(payload)
    claims["exp"] = datetime.utcnow() + timedelta(seconds=JWT_EXP_DELTA_SECONDS)
    return jwt.encode(claims, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def _new_state() -> str:
    # Cryptographically strong random state; we store it in a short-lived cookie
    return secrets.token_urlsafe(32)


def _build_reddit_client() -> asyncpraw.Reddit:
    """Centralized reddit client builder (keeps settings consistent)."""
    return asyncpraw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        redirect_uri=REDDIT_REDIRECT_URI,
        user_agent=REDDIT_USER_AGENT,
    )


@router.get("/reddit/login")
async def reddit_login():
    """Begin OAuth: redirect user to Reddit consent screen and set CSRF state cookie."""
    if not (REDDIT_REDIRECT_URI and FRONTEND_ORIGIN and REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="Missing required env vars")

    reddit = _build_reddit_client()

    state = _new_state()
    auth_url = reddit.auth.url(scopes=REDDIT_SCOPE.split(), state=state, duration="permanent")

    logger.info("Starting Reddit OAuth; redirect_uri=%s", REDDIT_REDIRECT_URI)

    # Set state cookie for CSRF protection (10 min TTL)
    # Clear any existing state cookies first, then set new one
    resp = RedirectResponse(auth_url)

    # Clear any existing state cookies with different domains
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", domain=None)  # Clear host-only
    if COOKIE_DOMAIN:
        resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", domain=COOKIE_DOMAIN)

    # Set new state cookie
    resp.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=600,
        path="/",
        domain=COOKIE_DOMAIN,  # Use configured domain or host-only if None
    )
    return resp


@router.get("/reddit/callback")
async def reddit_callback(request: Request):
    """
    OAuth redirect target. Exchanges 'code' for a refresh token and sets a session JWT cookie.
    On error, returns clear 4xx with details (instead of opaque 500).
    """
    if not (REDDIT_REDIRECT_URI and FRONTEND_ORIGIN and REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET):
        raise HTTPException(status_code=500, detail="Missing required env vars")

    # Reddit may send error=access_denied or other errors
    error = request.query_params.get("error")
    if error:
        raise HTTPException(status_code=400, detail=f"Reddit returned error: {error}")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state from Reddit callback")

    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    reddit = _build_reddit_client()

    try:
        # Exchange code -> tokens (code is single-use & short-lived)
        result = await reddit.auth.authorize(code)

        # asyncpraw: refresh token may be on reddit.auth.refresh_token or returned as str
        refresh_token = getattr(reddit.auth, "refresh_token", None) or (result if isinstance(result, str) else None)
        if not refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh token from Reddit (ensure duration=permanent and exact redirect URI).",
            )

        me = await reddit.user.me()

    except CoreResponseException as ex:
        # Log Reddit's error body for fast diagnosis
        status = None
        body = "<unavailable>"
        try:
            resp = getattr(ex, "response", None)
            if resp is not None:
                status = getattr(resp, "status", None)
                try:
                    body = await resp.text()  # aiohttp ClientResponse
                except Exception:
                    body = str(resp)
        except Exception:
            pass
        logger.error("Reddit token exchange failed: status=%s body=%s", status, body)
        raise HTTPException(status_code=400, detail=f"Reddit response error (HTTP {status})")
    except CoreOAuthException as ex:
        logger.exception("OAuthException during Reddit authorize")
        raise HTTPException(status_code=400, detail=f"OAuth error: {ex}")
    except CorePrawcoreException as ex:
        logger.exception("PRAWCore exception during Reddit authorize")
        raise HTTPException(status_code=400, detail=f"PRAW error: {ex}")
    except Exception as ex:
        # Try to surface any attached body even for unexpected exceptions
        body = None
        try:
            resp = getattr(ex, "response", None)
            if resp is not None:
                body = await resp.text()
        except Exception:
            pass
        logger.exception("Unexpected error during Reddit OAuth callback; body=%s", body)
        raise HTTPException(status_code=400, detail=f"Unexpected OAuth error: {ex}")
    finally:
        try:
            await reddit.close()
        except Exception:
            pass

    # Build short-lived session JWT (stores refresh token; consider server-side storage later)
    token = create_jwt(
        {
            "refresh_token": refresh_token,
            "name": getattr(me, "name", None),
            "icon_img": getattr(me, "icon_img", None),
        }
    )

    # Normalize frontend redirect (avoid double slashes)
    frontend_redirect = (FRONTEND_ORIGIN or "").rstrip("/") + "/"

    resp = RedirectResponse(frontend_redirect)
    resp.set_cookie(
        key=TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=JWT_EXP_DELTA_SECONDS,
        path="/",
        domain=COOKIE_DOMAIN,  # None => host-only (api.YOUR_DOMAIN)
    )
    # Clear state cookie
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", domain=None)
    if COOKIE_DOMAIN:
        resp.delete_cookie(OAUTH_STATE_COOKIE, path="/", domain=COOKIE_DOMAIN)
    return resp


# === NEW: whoami endpoint for the frontend to confirm auth ===
@router.get("/me")
async def auth_me(request: Request):
    """
    Return the basic identity from the session JWT (set in `reddit_token` cookie).
    401 if missing/expired/invalid.
    """
    token = request.cookies.get(TOKEN_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Minimal, stable shape for frontend
    return {
        "authenticated": True,
        "name": payload.get("name"),
        "icon_img": payload.get("icon_img"),
        "exp": payload.get("exp"),
    }


# === NEW: logout endpoint (clears cookie) ===
@router.post("/logout")
@router.get("/logout")  # be liberal in what we accept
async def auth_logout():
    resp = Response(content='{"ok":true}', media_type="application/json")
    # Delete cookie for host-only and configured domain
    resp.delete_cookie(TOKEN_COOKIE, path="/", domain=None)
    if COOKIE_DOMAIN:
        resp.delete_cookie(TOKEN_COOKIE, path="/", domain=COOKIE_DOMAIN)
    return resp
