from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from market_simulator.db.enums import SubscriptionStatus, UserStatus
from market_simulator.db.models.user import Plan, User, UserPlanSubscription


class ProvisioningError(ValueError):
    pass


@dataclass(frozen=True)
class ProvisioningResult:
    user_id: str
    email: str
    user_action: str
    plan_code: str
    plan_action: str
    dry_run: bool = False


def provision_user(
    db: Session,
    *,
    email: str,
    display_name: str | None = None,
    update_display_name: bool = True,
    status: str = UserStatus.ACTIVE.value,
    update_status: bool = False,
    plan_code: str = "FREE",
    user_id: str | None = None,
    provider: str | None = None,
    dry_run: bool = False,
) -> ProvisioningResult:
    normalized_email = _normalize_email(email)
    normalized_plan_code = _normalize_plan_code(plan_code)
    user_uuid = _parse_user_id(user_id) if user_id else None
    normalized_status = _normalize_user_status(status)

    plan = db.query(Plan).filter(Plan.code == normalized_plan_code).first()
    if plan is None:
        raise ProvisioningError(f"Unknown plan code: {normalized_plan_code}")
    if not plan.is_active:
        raise ProvisioningError(f"Plan is not active: {normalized_plan_code}")

    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    user_action = "existing"

    if user is None:
        user = User(
            id=user_uuid or uuid.uuid4(),
            email=normalized_email,
            password_hash=None,
            display_name=display_name,
            status=normalized_status,
        )
        db.add(user)
        db.flush()
        user_action = "created"
    else:
        if user_uuid is not None and user.id != user_uuid:
            raise ProvisioningError(
                f"Existing user for {normalized_email} has id {user.id}, not {user_uuid}"
            )

        changed = False
        if update_display_name and display_name is not None and user.display_name != display_name:
            user.display_name = display_name
            changed = True
        if update_status and _status_value(user.status) != normalized_status:
            user.status = normalized_status
            changed = True
        if changed:
            db.flush()
            user_action = "updated"

    now = datetime.now(timezone.utc)
    active_subscription = (
        db.query(UserPlanSubscription)
        .filter(
            UserPlanSubscription.user_id == user.id,
            UserPlanSubscription.plan_id == plan.id,
            UserPlanSubscription.status == SubscriptionStatus.ACTIVE,
            UserPlanSubscription.starts_at <= now,
            or_(UserPlanSubscription.ends_at.is_(None), UserPlanSubscription.ends_at > now),
        )
        .first()
    )

    plan_action = "existing"
    if active_subscription is None:
        subscription = UserPlanSubscription(
            id=uuid.uuid4(),
            user_id=user.id,
            plan_id=plan.id,
            status=SubscriptionStatus.ACTIVE,
            starts_at=now,
            ends_at=None,
            auto_renew=False,
            provider=provider,
            provider_subscription_id=None,
        )
        db.add(subscription)
        db.flush()
        plan_action = "assigned"

    result = ProvisioningResult(
        user_id=str(user.id),
        email=normalized_email,
        user_action=user_action,
        plan_code=normalized_plan_code,
        plan_action=plan_action,
        dry_run=dry_run,
    )

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return result


def format_provisioning_result(result: ProvisioningResult) -> str:
    prefix = "dry-run " if result.dry_run else ""
    return (
        f"{prefix}user={result.user_action} user_id={result.user_id} "
        f"email={result.email} plan={result.plan_action} plan_code={result.plan_code}"
    )


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        raise ProvisioningError("A valid email address is required")
    return normalized


def _normalize_plan_code(plan_code: str) -> str:
    normalized = plan_code.strip().upper()
    if not normalized:
        raise ProvisioningError("A plan code is required")
    return normalized


def _normalize_user_status(status: str) -> str:
    normalized = status.strip().upper()
    allowed = {item.value for item in UserStatus}
    if normalized not in allowed:
        raise ProvisioningError(f"Unknown user status: {status}")
    return normalized


def _parse_user_id(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(user_id)
    except ValueError as exc:
        raise ProvisioningError(f"Invalid user id: {user_id}") from exc


def _status_value(status: UserStatus | str) -> str:
    return status.value if isinstance(status, UserStatus) else str(status)
