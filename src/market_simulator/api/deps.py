from __future__ import annotations

import uuid

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from market_simulator.db.models.user import User
from market_simulator.db.session import get_db
from market_simulator.settings import get_settings


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    resolved_user_id = x_user_id or settings.dev_default_user_id

    if not resolved_user_id:
        raise HTTPException(status_code=401, detail="Missing authenticated user")

    try:
        user_uuid = uuid.UUID(str(resolved_user_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid user id") from exc

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if str(user.status) != "ACTIVE":
        raise HTTPException(status_code=403, detail="User is not active")

    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "status": str(user.status),
    }