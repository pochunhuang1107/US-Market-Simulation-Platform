from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from market_simulator.auth.current_user import CurrentUser, resolve_current_user
from market_simulator.db.session import get_db
from market_simulator.settings import get_settings


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> CurrentUser:
    settings = get_settings()
    return resolve_current_user(db=db, settings=settings, x_user_id=x_user_id)
