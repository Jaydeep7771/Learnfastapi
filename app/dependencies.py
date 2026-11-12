"""Composable dependencies: the app's wiring layer.

WHY Depends beats a service locator / global singletons:
  * the dependency graph is declared in the signature, so it is visible and typed
  * FastAPI caches each dependency once per request (sub-dependencies are shared)
  * any node can be swapped in tests with `app.dependency_overrides[...]`
"""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import decode_token
from app.db.session import get_session
from app.models import User

# tokenUrl is what makes the "Authorize" button appear in /docs.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


class Pagination:
    """Class dependency: one object, reusable on every list route."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]


async def get_current_user(token: TokenDep, session: SessionDep) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, expect="access")
    except jwt.PyJWTError as exc:
        raise credentials_error from exc

    user = await session.scalar(select(User).where(User.email == payload.get("sub")))
    if user is None:
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[[User], User]:
    """Dependency FACTORY: returns a fresh guard closed over the allowed roles.

    Usage: `user: Annotated[User, Depends(require_role("admin"))]`
    It composes on top of get_current_user, which FastAPI resolves exactly once.
    """

    def guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of roles: {', '.join(roles)}",
            )
        return user

    return guard


AdminUser = Annotated[User, Depends(require_role("admin"))]
