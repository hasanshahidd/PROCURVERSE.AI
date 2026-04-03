"""
Authentication Service for Procure-AI
Uses PyJWT for token creation/verification, with a fallback to in-memory token store
if PyJWT is not installed.
"""

import os
import hmac
import hashlib
import base64
import json
import time
import secrets
import logging
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT secret — read from env, with a hardcoded fallback for demo environments
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "procure-ai-demo-secret-change-in-production-2024")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 24 * 60 * 60  # 24 hours

# Sprint 10: When false (default), unauthenticated requests get a demo user.
# Set AUTH_REQUIRED=true in production to enforce real JWT tokens.
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").lower() == "true"

# HTTPBearer scheme (used as a FastAPI dependency)
security = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Determine which JWT backend is available
# ---------------------------------------------------------------------------
_JWT_BACKEND: str = "none"

try:
    import jwt as _pyjwt  # PyJWT ≥ 2.x
    _JWT_BACKEND = "pyjwt"
    logger.info("[AUTH] Using PyJWT backend")
except ImportError:
    pass

if _JWT_BACKEND == "none":
    # Fallback: hand-rolled HMAC tokens (no external dependency)
    logger.info("[AUTH] PyJWT not available — using built-in HMAC token backend")

# ---------------------------------------------------------------------------
# In-memory token blacklist / revocation store (for logout support)
# Maps token -> expiry timestamp; entries expire naturally.
# ---------------------------------------------------------------------------
_revoked_tokens: Dict[str, float] = {}


def _purge_expired_revocations() -> None:
    """Remove expired entries from the revocation store to avoid memory leaks."""
    now = time.time()
    expired = [t for t, exp in _revoked_tokens.items() if exp < now]
    for t in expired:
        _revoked_tokens.pop(t, None)


# ---------------------------------------------------------------------------
# HMAC-based token helpers (fallback when PyJWT is absent)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _hmac_create_token(payload: Dict[str, Any]) -> str:
    """
    Create a signed token: base64url(header).base64url(payload).hmac_signature
    This is a simplified JWT-like format — HS256 signature over header.payload.
    """
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
    signature = _b64url_encode(sig)
    return f"{header}.{body}.{signature}"


def _hmac_verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode an HMAC token.  Raises HTTPException 401 on any failure.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed token")

        header_b64, body_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{body_b64}".encode()
        expected_sig = hmac.new(JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        expected_b64 = _b64url_encode(expected_sig)

        if not hmac.compare_digest(sig_b64, expected_b64):
            raise ValueError("Invalid signature")

        payload = json.loads(_b64url_decode(body_b64))

        exp = payload.get("exp")
        if exp and time.time() > exp:
            raise ValueError("Token expired")

        return payload
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_access_token(data: Dict[str, Any]) -> str:
    """
    Create a signed access token that expires in JWT_EXPIRY_SECONDS.
    Adds 'iat' and 'exp' claims automatically.
    """
    payload = dict(data)
    now = time.time()
    payload["iat"] = now
    payload["exp"] = now + JWT_EXPIRY_SECONDS

    if _JWT_BACKEND == "pyjwt":
        import jwt as _pyjwt
        return _pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    # HMAC fallback
    return _hmac_create_token(payload)


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify a token and return its payload dict.
    Raises HTTPException 401 if invalid, expired, or revoked.
    """
    _purge_expired_revocations()

    if token in _revoked_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _JWT_BACKEND == "pyjwt":
        import jwt as _pyjwt
        try:
            payload = _pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except _pyjwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except _pyjwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # HMAC fallback
    return _hmac_verify_token(token)


def revoke_token(token: str) -> None:
    """
    Add a token to the revocation list.
    Used by the logout endpoint so the token cannot be reused.
    """
    try:
        payload = verify_token(token)
        exp = payload.get("exp", time.time() + JWT_EXPIRY_SECONDS)
        _revoked_tokens[token] = exp
    except HTTPException:
        # Already invalid — nothing to revoke
        pass


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
) -> Dict[str, Any]:
    """
    FastAPI dependency — extracts and validates the bearer token.

    In demo mode (AUTH_REQUIRED=false, the default), unauthenticated requests
    receive a synthetic admin user so the app works without login during
    development.  In production (AUTH_REQUIRED=true), a missing or invalid
    token raises HTTP 401.
    """
    if credentials and credentials.credentials:
        return verify_token(credentials.credentials)

    # No credentials provided
    if not AUTH_REQUIRED:
        return {"sub": "demo@procure-ai.com", "role": "admin", "name": "Demo User"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency — returns the authenticated user dict if a valid token is
    present, or None if no Authorization header was sent.
    Raises 401 only when a token IS present but invalid (not when absent).
    """
    if not credentials or not credentials.credentials:
        return None
    # Token present — it must be valid
    return verify_token(credentials.credentials)
