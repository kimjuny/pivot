"""Authentication API endpoints.

This module provides endpoints for user authentication including login.
"""

import os
from datetime import UTC, datetime
from typing import Any

import bcrypt
from app.api.dependencies import get_db
from app.models.access import Role
from app.models.user import CurrentUserResponse, User, UserLogin, UserResponse
from app.services.permission_service import PermissionService
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlmodel import Session, select

# Security configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# HTTP Bearer token security
security = HTTPBearer()

router = APIRouter()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password.

    Args:
        plain_password: The plain text password to verify.
        hashed_password: The hashed password to compare against.

    Returns:
        True if the password matches, False otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Hash a password for storage.

    Args:
        password: The plain text password to hash.

    Returns:
        The hashed password.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict[str, Any]) -> str:
    """Create a JWT access token.

    Args:
        data: The data to encode in the token.

    Returns:
        The encoded JWT token.
    """
    to_encode = data.copy()
    to_encode.update(
        {"exp": datetime.now(UTC).timestamp() + ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    )
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_db),
) -> User:
    """Get the current authenticated user from the JWT token.

    Args:
        credentials: The HTTP Bearer credentials containing the JWT token.
        session: The database session.

    Returns:
        The authenticated user.

    Raises:
        HTTPException: If the token is invalid or the user doesn't exist.
    """
    return resolve_user_from_access_token(credentials.credentials, session)


def resolve_user_from_access_token(token: str, session: Session) -> User:
    """Resolve one user from a raw bearer access token.

    Args:
        token: Encoded JWT access token.
        session: Active database session.

    Returns:
        Authenticated user model.

    Raises:
        HTTPException: If the token is invalid or the user doesn't exist.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as err:
        raise credentials_exception from err

    user = session.get(User, user_id)
    if user is None:
        raise credentials_exception
    if user.status != "active":
        raise credentials_exception

    return user


@router.post("/auth/login", response_model=UserResponse)
async def login(
    login_data: UserLogin, session: Session = Depends(get_db)
) -> UserResponse:
    """Authenticate a user and return an access token.

    Args:
        login_data: The user's login credentials.
        session: The database session.

    Returns:
        The user data with access token.

    Raises:
        HTTPException: If the username or password is incorrect.
    """
    user = session.exec(
        select(User).where(User.username == login_data.username)
    ).first()

    if user is None or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
        )

    if user.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User id is missing",
        )
    role = session.get(Role, user.role_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User role is missing",
        )

    access_token = create_access_token(data={"sub": str(user.id)})

    return UserResponse(
        id=user.id,
        username=user.username,
        role=role.key,
        permissions=sorted(PermissionService(session).get_user_permission_keys(user)),
        access_token=access_token,
    )


@router.get("/auth/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> CurrentUserResponse:
    """Get the current authenticated user.

    Args:
        current_user: The authenticated user.

    Returns:
        The current user.
    """
    role = session.get(Role, current_user.role_id)
    if role is None or current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User role is missing",
        )
    return CurrentUserResponse(
        id=current_user.id,
        username=current_user.username,
        role=role.key,
        permissions=sorted(
            PermissionService(session).get_user_permission_keys(current_user)
        ),
    )
