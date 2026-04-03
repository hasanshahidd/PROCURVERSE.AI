"""
Authentication Routes for Procure-AI
POST /api/auth/login   — validate credentials, return JWT
POST /api/auth/logout  — revoke token (stateless JWT + revocation list)
GET  /api/auth/me      — return current user from JWT
"""

import os
import hmac
import logging
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr

from backend.services.auth_service import (
    create_access_token,
    verify_token,
    revoke_token,
    get_current_user,
    security,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# Built-in demo users
# Passwords are read from env vars; hardcoded values are used as demo fallbacks.
# ---------------------------------------------------------------------------

def _build_users() -> Dict[str, Dict[str, Any]]:
    return {
        "admin@procurement.ai": {
            "password": os.getenv("AUTH_ADMIN_PASSWORD", "Admin@2024!"),
            "role": "admin",
            "name": "Admin",
            "email": "admin@procurement.ai",
        },
        "hassan@liztek.com": {
            "password": os.getenv("AUTH_HASSAN_PASSWORD", "Liztek@2024!"),
            "role": "manager",
            "name": "Hassan",
            "email": "hassan@liztek.com",
        },
        "finance@procure.ai": {
            "password": os.getenv("AUTH_FINANCE_PASSWORD", "Finance@2024!"),
            "role": "finance",
            "name": "Finance User",
            "email": "finance@procure.ai",
        },
    }


# Also accept the old demo passwords from the frontend (1234 / admin)
# so existing users aren't locked out immediately.
_LEGACY_CREDENTIALS = {
    "admin@procurement.ai": ["1234"],
    "hassan@liztek.com": ["1234"],
    "admin": ["admin"],          # legacy "admin" username
}


def _verify_password(email: str, password: str) -> bool:
    """
    Check password against the primary USERS dict.
    Falls back to legacy demo passwords for backwards compatibility.
    """
    users = _build_users()

    # Primary check (new strong passwords)
    user = users.get(email)
    if user:
        if hmac.compare_digest(password, user["password"]):
            return True

    # Legacy fallback (old frontend passwords)
    legacy = _LEGACY_CREDENTIALS.get(email, [])
    return any(hmac.compare_digest(password, lp) for lp in legacy)


def _get_user_record(email: str) -> Optional[Dict[str, Any]]:
    """Return user metadata (without password) or None if unknown."""
    users = _build_users()
    # Map legacy "admin" username to the real record
    if email == "admin":
        email = "admin@procurement.ai"
    user = users.get(email)
    if user:
        return {k: v for k, v in user.items() if k != "password"}
    return None


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


class LogoutResponse(BaseModel):
    message: str


class MeResponse(BaseModel):
    email: str
    name: str
    role: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    """
    Authenticate with email + password.
    Returns a signed JWT on success.
    """
    email = (body.email or "").strip().lower()
    password = body.password or ""

    if not _verify_password(email, password):
        logger.warning(f"[AUTH] Failed login attempt for: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user = _get_user_record(email)
    if not user:
        # Should not happen since _verify_password passed, but guard anyway
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User record not found.",
        )

    token_payload = {
        "sub": user["email"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }
    access_token = create_access_token(token_payload)

    logger.info(f"[AUTH] Successful login: {user['email']} (role={user['role']})")

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """
    Logout endpoint.  Revokes the current token so it cannot be reused.
    The frontend should also clear its local token storage.
    """
    if credentials and credentials.credentials:
        revoke_token(credentials.credentials)
        logger.info("[AUTH] Token revoked via logout")

    return LogoutResponse(message="Logged out successfully.")


@router.get("/me", response_model=MeResponse)
async def get_me(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """
    Return the currently authenticated user's profile.
    Requires a valid Bearer token.
    """
    user = get_current_user(credentials)

    return MeResponse(
        email=user.get("email") or user.get("sub", ""),
        name=user.get("name", ""),
        role=user.get("role", ""),
    )
