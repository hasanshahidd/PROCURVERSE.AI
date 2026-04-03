"""
RBAC (Role-Based Access Control) — Sprint 10 Security
Provides role-checking dependencies for FastAPI endpoints.
"""
from __future__ import annotations
import logging
from typing import List
from fastapi import Depends, HTTPException, status
from backend.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

# Role hierarchy: higher roles include lower role permissions
ROLE_HIERARCHY = {
    "admin": ["admin", "director", "manager", "approver", "user", "viewer"],
    "director": ["director", "manager", "approver", "user", "viewer"],
    "manager": ["manager", "approver", "user", "viewer"],
    "approver": ["approver", "user", "viewer"],
    "user": ["user", "viewer"],
    "viewer": ["viewer"],
}


def require_role(allowed_roles: List[str]):
    """FastAPI dependency that checks if the current user has one of the allowed roles."""
    async def role_checker(current_user: dict = Depends(get_current_user)):
        user_role = (current_user.get("role") or "user").lower()
        # Check if user's role (or any role it includes) matches allowed
        effective_roles = ROLE_HIERARCHY.get(user_role, [user_role])
        if not any(r in allowed_roles for r in effective_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' not authorized. Required: {allowed_roles}",
            )
        return current_user
    return role_checker


def require_auth():
    """Simple auth check — any authenticated user."""
    async def auth_checker(current_user: dict = Depends(get_current_user)):
        return current_user
    return auth_checker
