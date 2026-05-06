"""Service helpers for signing and validating surface-scoped access tokens."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

_SURFACE_TOKEN_SECRET_KEY = os.getenv(
    "SECRET_KEY", "your-secret-key-change-in-production"
)
_SURFACE_TOKEN_ALGORITHM = "HS256"
_SURFACE_TOKEN_LIFETIME = timedelta(hours=8)
_SURFACE_TOKEN_KIND = "surface_session"


class SurfaceTokenError(Exception):
    """Base error for surface access token failures."""


class SurfaceTokenValidationError(SurfaceTokenError):
    """Raised when a surface access token is missing or invalid."""


@dataclass(frozen=True)
class SurfaceTokenClaims:
    """Validated claims extracted from one surface access token."""

    surface_session_id: str
    username: str


class SurfaceTokenService:
    """Issue and validate short-lived tokens bound to one surface session."""

    @staticmethod
    def create_surface_token(*, surface_session_id: str, username: str) -> str:
        """Create one signed surface access token.

        Args:
            surface_session_id: Backend-issued surface session identifier.
            username: Username that owns the surface session.

        Returns:
            Encoded JWT token.
        """
        now = datetime.now(UTC)
        payload = {
            "kind": _SURFACE_TOKEN_KIND,
            "surface_session_id": surface_session_id,
            "username": username,
            "iat": int(now.timestamp()),
            "exp": int((now + _SURFACE_TOKEN_LIFETIME).timestamp()),
        }
        return jwt.encode(
            payload,
            _SURFACE_TOKEN_SECRET_KEY,
            algorithm=_SURFACE_TOKEN_ALGORITHM,
        )

    @staticmethod
    def validate_surface_token(token: str) -> SurfaceTokenClaims:
        """Validate one signed surface access token.

        Args:
            token: Encoded surface JWT.

        Returns:
            Validated claims extracted from the token.

        Raises:
            SurfaceTokenValidationError: If the token is invalid or incomplete.
        """
        try:
            payload = jwt.decode(
                token,
                _SURFACE_TOKEN_SECRET_KEY,
                algorithms=[_SURFACE_TOKEN_ALGORITHM],
            )
        except JWTError as err:
            raise SurfaceTokenValidationError("Surface token is invalid.") from err

        if payload.get("kind") != _SURFACE_TOKEN_KIND:
            raise SurfaceTokenValidationError("Surface token kind is invalid.")

        surface_session_id = payload.get("surface_session_id")
        username = payload.get("username")
        if not isinstance(surface_session_id, str) or not surface_session_id:
            raise SurfaceTokenValidationError(
                "Surface token is missing surface_session_id."
            )
        if not isinstance(username, str) or not username:
            raise SurfaceTokenValidationError("Surface token is missing username.")

        return SurfaceTokenClaims(
            surface_session_id=surface_session_id,
            username=username,
        )
