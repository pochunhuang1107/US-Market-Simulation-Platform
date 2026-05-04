from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from market_simulator.auth.current_user import (
    PROVIDER_NOT_CONFIGURED_DETAIL,
    resolve_current_user,
)
from market_simulator.db.enums import UserStatus
from market_simulator.settings import Settings


DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def _assert_auth_error(exc_info, *, status_code: int, detail: str) -> None:
    exc = exc_info.value
    assert exc.status_code == status_code
    assert exc.detail == detail


def test_dev_default_user_resolves_current_user(db_session, create_user):
    create_user(user_id=DEV_USER_ID, email="dev-default@example.com")

    current_user = resolve_current_user(
        db=db_session,
        settings=Settings(env="local", auth_mode="dev", dev_default_user_id=DEV_USER_ID),
    )

    assert current_user.id == DEV_USER_ID
    assert current_user["id"] == DEV_USER_ID
    assert current_user.email == "dev-default@example.com"
    assert current_user.status == UserStatus.ACTIVE.value


def test_x_user_id_override_resolves_only_in_dev_mode(db_session, create_user):
    create_user(user_id=DEV_USER_ID, email="dev-default@example.com")
    header_user_id = str(uuid.uuid4())
    create_user(user_id=header_user_id, email="header-user@example.com")

    current_user = resolve_current_user(
        db=db_session,
        settings=Settings(env="local", auth_mode="dev", dev_default_user_id=DEV_USER_ID),
        x_user_id=header_user_id,
    )
    assert current_user.id == header_user_id

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=Settings(env="local", auth_mode="required", dev_default_user_id=DEV_USER_ID),
            x_user_id=header_user_id,
        )

    _assert_auth_error(
        exc_info,
        status_code=401,
        detail=PROVIDER_NOT_CONFIGURED_DETAIL,
    )


def test_dev_mode_rejects_invalid_x_user_id(db_session):
    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=Settings(env="local", auth_mode="dev", dev_default_user_id=DEV_USER_ID),
            x_user_id="not-a-uuid",
        )

    _assert_auth_error(exc_info, status_code=401, detail="Invalid user id")


def test_dev_mode_rejects_missing_user(db_session):
    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=Settings(env="local", auth_mode="dev", dev_default_user_id=DEV_USER_ID),
            x_user_id=str(uuid.uuid4()),
        )

    _assert_auth_error(exc_info, status_code=401, detail="User not found")


def test_dev_mode_rejects_inactive_user(db_session, create_user):
    user = create_user(email="inactive-user@example.com")
    user.status = UserStatus.SUSPENDED
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=Settings(env="local", auth_mode="dev", dev_default_user_id=DEV_USER_ID),
            x_user_id=str(user.id),
        )

    _assert_auth_error(exc_info, status_code=403, detail="User is not active")


def test_protected_env_rejects_x_user_id_and_reports_provider_not_configured(
    db_session,
    create_user,
):
    user = create_user(email="protected-user@example.com")

    for env in ("beta", "production"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_current_user(
                db=db_session,
                settings=Settings(env=env, auth_mode="dev", dev_default_user_id=DEV_USER_ID),
                x_user_id=str(user.id),
            )

        _assert_auth_error(
            exc_info,
            status_code=401,
            detail=PROVIDER_NOT_CONFIGURED_DETAIL,
        )


def test_protected_env_reports_provider_not_configured_without_header(db_session):
    for env in ("beta", "production"):
        with pytest.raises(HTTPException) as exc_info:
            resolve_current_user(
                db=db_session,
                settings=Settings(env=env, auth_mode="required", dev_default_user_id=DEV_USER_ID),
            )

        _assert_auth_error(
            exc_info,
            status_code=401,
            detail=PROVIDER_NOT_CONFIGURED_DETAIL,
        )
