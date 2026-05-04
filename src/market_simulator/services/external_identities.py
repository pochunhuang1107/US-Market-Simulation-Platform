from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from market_simulator.db.models.user import User, UserExternalIdentity


class ExternalIdentityError(ValueError):
    pass


class ExternalIdentityConflict(ExternalIdentityError):
    pass


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if not normalized:
        raise ExternalIdentityError("An external provider is required")
    return normalized


def normalize_subject(subject: str) -> str:
    normalized = subject.strip()
    if not normalized:
        raise ExternalIdentityError("An external subject is required")
    return normalized


def find_external_identity(
    db: Session,
    *,
    provider: str,
    subject: str,
) -> UserExternalIdentity | None:
    return (
        db.query(UserExternalIdentity)
        .filter(
            UserExternalIdentity.provider == normalize_provider(provider),
            UserExternalIdentity.subject == normalize_subject(subject),
        )
        .first()
    )


def link_external_identity(
    db: Session,
    *,
    user: User,
    provider: str,
    subject: str,
    email_at_link_time: str | None = None,
) -> tuple[UserExternalIdentity, str]:
    normalized_provider = normalize_provider(provider)
    normalized_subject = normalize_subject(subject)
    identity = find_external_identity(
        db,
        provider=normalized_provider,
        subject=normalized_subject,
    )

    if identity is not None:
        if identity.user_id != user.id:
            raise ExternalIdentityConflict(
                f"External identity {normalized_provider}/{normalized_subject} "
                "is already linked to another user"
            )
        return identity, "existing"

    identity = UserExternalIdentity(
        id=uuid.uuid4(),
        user_id=user.id,
        provider=normalized_provider,
        subject=normalized_subject,
        email_at_link_time=email_at_link_time,
    )
    db.add(identity)
    db.flush()
    return identity, "created"
