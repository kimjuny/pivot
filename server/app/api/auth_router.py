"""Authenticated API Router for protected endpoints.

This module provides type aliases and utilities for authenticated endpoints.

Example:
    from app.api.auth_router import CurrentUser
    from app.api.dependencies import get_db

    @router.get("/protected-resource")
    async def get_protected(
        db: Session = Depends(get_db),
        current_user: CurrentUser,
    ):
        return {"user_id": current_user.id}
"""

from typing import Annotated

from app.api.auth import get_current_user
from app.models.user import User
from fastapi import Depends

# Type alias for current user - User is a Pydantic model so this works
CurrentUser = Annotated[User, Depends(get_current_user)]

# Export for convenient access
__all__ = [
    "CurrentUser",
]
