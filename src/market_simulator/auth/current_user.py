from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, overload

from fastapi import HTTPException
from sqlalchemy.orm import Session

from market_simulator.db.enums import UserStatus
from market_simulator.db.models.user import User
from market_simulator.settings import Settings


PROVIDER_NOT_CONFIGURED_DETAIL = "Authenticated user provider is not configured."


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    display_name: str | None
    status: str

    @overload
    def __getitem__(self, key: Literal["id", "email", "display_name", "status"]) -> str | None:
        ...

    @overload
    def __getitem__(self, key: str) -> str | None:
        ...

    def __getitem__(self, key: str) -> str | None:
        if key == "id":
            return self.id
        if key == "email":
            return self.email
        if key == "display_name":
            return self.display_name
        if key == "status":
            return self.status
        raise KeyError(key)

    def as_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
        }


def resolve_current_user(
    *,
    db: Session,
    settings: Settings,
    x_user_id: str | None = None,
) -> CurrentUser:
    if settings.is_dev_auth_enabled:
        return _resolve_dev_current_user(
            db=db,
            default_user_id=settings.dev_default_user_id,
            x_user_id=x_user_id,
        )

    return _resolve_required_current_user()


def _resolve_required_current_user() -> CurrentUser:
    raise HTTPException(status_code=401, detail=PROVIDER_NOT_CONFIGURED_DETAIL)


def _resolve_dev_current_user(
    *,
    db: Session,
    default_user_id: str | None,
    x_user_id: str | None,
) -> CurrentUser:
    resolved_user_id = x_user_id or default_user_id

    if not resolved_user_id:
        raise HTTPException(status_code=401, detail="Missing authenticated user")

    try:
        user_uuid = uuid.UUID(str(resolved_user_id))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid user id") from exc

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not _is_active_user(user):
        raise HTTPException(status_code=403, detail="User is not active")

    return CurrentUser(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        status=_status_value(user.status),
    )


def _is_active_user(user: User) -> bool:
    return _status_value(user.status) == UserStatus.ACTIVE.value


def _status_value(status: UserStatus | str) -> str:
    return status.value if isinstance(status, UserStatus) else str(status)
