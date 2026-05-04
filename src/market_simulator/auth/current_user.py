from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from typing import Literal, overload
from urllib.error import URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from market_simulator.db.enums import UserStatus
from market_simulator.db.models.user import User
from market_simulator.services.external_identities import (
    ExternalIdentityError,
    find_external_identity,
    link_external_identity,
    normalize_provider,
)
from market_simulator.settings import Settings


PROVIDER_NOT_CONFIGURED_DETAIL = "Authenticated user provider is not configured."
MISSING_BEARER_TOKEN_DETAIL = "Missing bearer token"
INVALID_BEARER_TOKEN_DETAIL = "Invalid bearer token"
USER_NOT_PROVISIONED_DETAIL = "Authenticated user is not provisioned."

_SUPPORTED_JWT_ALGORITHMS = {"RS256"}
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_JWKS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


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
    authorization: str | None = None,
    x_user_id: str | None = None,
) -> CurrentUser:
    if settings.is_dev_auth_enabled:
        return _resolve_dev_current_user(
            db=db,
            default_user_id=settings.dev_default_user_id,
            x_user_id=x_user_id,
        )

    if settings.is_oidc_auth_enabled:
        return _resolve_oidc_current_user(
            db=db,
            settings=settings,
            authorization=authorization,
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


def _resolve_oidc_current_user(
    *,
    db: Session,
    settings: Settings,
    authorization: str | None,
) -> CurrentUser:
    token = _extract_bearer_token(authorization)
    claims = _decode_and_validate_jwt(token=token, settings=settings)

    email = _claim_as_string(claims, settings.oidc_email_claim)
    subject = _claim_as_string(claims, settings.oidc_subject_claim)
    if not subject:
        raise HTTPException(status_code=401, detail="Token subject claim is missing")

    display_name = _claim_as_string(claims, settings.oidc_display_name_claim)
    try:
        provider = normalize_provider(settings.oidc_provider_name)
    except ExternalIdentityError as exc:
        raise HTTPException(status_code=401, detail=PROVIDER_NOT_CONFIGURED_DETAIL) from exc

    identity = find_external_identity(db, provider=provider, subject=subject)
    if identity is not None:
        user = identity.user
        if user is None:
            raise HTTPException(status_code=401, detail=USER_NOT_PROVISIONED_DETAIL)
        if not _is_active_user(user):
            raise HTTPException(status_code=403, detail="User is not active")
        return _current_user_from_user(user, token_display_name=display_name)

    if not settings.oidc_allow_email_linking:
        raise HTTPException(status_code=401, detail=USER_NOT_PROVISIONED_DETAIL)

    if not email:
        raise HTTPException(status_code=401, detail="Token email claim is missing")

    normalized_email = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if user is None:
        raise HTTPException(status_code=401, detail=USER_NOT_PROVISIONED_DETAIL)

    if not _is_active_user(user):
        raise HTTPException(status_code=403, detail="User is not active")

    try:
        link_external_identity(
            db,
            user=user,
            provider=provider,
            subject=subject,
            email_at_link_time=normalized_email,
        )
        db.commit()
    except ExternalIdentityError as exc:
        db.rollback()
        raise HTTPException(status_code=401, detail=USER_NOT_PROVISIONED_DETAIL) from exc

    return _current_user_from_user(user, token_display_name=display_name)


def _current_user_from_user(user: User, *, token_display_name: str | None = None) -> CurrentUser:
    return CurrentUser(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name or token_display_name,
        status=_status_value(user.status),
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail=MISSING_BEARER_TOKEN_DETAIL)

    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise HTTPException(status_code=401, detail="Malformed Authorization header")

    return parts[1]


def _decode_and_validate_jwt(*, token: str, settings: Settings) -> dict[str, Any]:
    try:
        header, payload, signature, signing_input = _split_jwt(token)
        algorithm = header.get("alg")
        if algorithm not in _SUPPORTED_JWT_ALGORITHMS:
            raise ValueError("Unsupported JWT algorithm")

        key = _select_jwks_key(header=header, jwks=_get_jwks(settings))
        _verify_rs256_signature(
            signing_input=signing_input,
            signature=signature,
            key=key,
        )
        _validate_registered_claims(payload, settings=settings)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=INVALID_BEARER_TOKEN_DETAIL) from exc

    return payload


def _split_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError("JWT must have three non-empty segments")

    header = json.loads(_base64url_decode(parts[0]))
    payload = json.loads(_base64url_decode(parts[1]))
    signature = _base64url_decode(parts[2])
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("JWT header and payload must be JSON objects")

    return header, payload, signature, signing_input


def _select_jwks_key(*, header: dict[str, Any], jwks: dict[str, Any]) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise ValueError("JWKS keys must be a list")

    key_id = header.get("kid")
    algorithm = header.get("alg")
    for key in keys:
        if not isinstance(key, dict):
            continue
        if key_id and key.get("kid") != key_id:
            continue
        if key.get("kty") != "RSA":
            continue
        if key.get("alg") and key.get("alg") != algorithm:
            continue
        if "n" in key and "e" in key:
            return key

    raise ValueError("No matching JWKS key found")


def _verify_rs256_signature(
    *,
    signing_input: bytes,
    signature: bytes,
    key: dict[str, Any],
) -> None:
    modulus = _jwk_int(key["n"])
    exponent = _jwk_int(key["e"])
    key_size_bytes = (modulus.bit_length() + 7) // 8
    if len(signature) != key_size_bytes:
        raise ValueError("Invalid RSA signature length")

    decrypted = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(
        key_size_bytes,
        "big",
    )
    digest = hashlib.sha256(signing_input).digest()
    expected_suffix = _SHA256_DIGEST_INFO_PREFIX + digest

    if not decrypted.startswith(b"\x00\x01") or not decrypted.endswith(expected_suffix):
        raise ValueError("Invalid RSA signature")

    padding_end = key_size_bytes - len(expected_suffix) - 1
    if padding_end < 10 or decrypted[2:padding_end] != b"\xff" * (padding_end - 2):
        raise ValueError("Invalid RSA signature padding")
    if decrypted[padding_end] != 0:
        raise ValueError("Invalid RSA signature separator")


def _validate_registered_claims(payload: dict[str, Any], *, settings: Settings) -> None:
    now = datetime.now(timezone.utc).timestamp()
    expiration = payload.get("exp")
    if not isinstance(expiration, int | float):
        raise ValueError("Token exp claim is missing")
    if expiration <= now:
        raise HTTPException(status_code=401, detail="Token is expired")

    not_before = payload.get("nbf")
    if isinstance(not_before, int | float) and not_before > now:
        raise ValueError("Token is not active yet")

    if settings.oidc_issuer and payload.get("iss") != settings.oidc_issuer:
        raise ValueError("Token issuer is invalid")

    if settings.oidc_audience and not _audience_matches(payload.get("aud"), settings.oidc_audience):
        raise ValueError("Token audience is invalid")


def _audience_matches(token_audience: Any, expected_audience: str) -> bool:
    if isinstance(token_audience, str):
        return token_audience == expected_audience
    if isinstance(token_audience, list):
        return expected_audience in token_audience
    return False


def _get_jwks(settings: Settings) -> dict[str, Any]:
    if not settings.oidc_jwks_url:
        raise HTTPException(status_code=401, detail=PROVIDER_NOT_CONFIGURED_DETAIL)

    now = time.monotonic()
    cached = _JWKS_CACHE.get(settings.oidc_jwks_url)
    if cached and cached[0] > now:
        return cached[1]

    try:
        request = Request(settings.oidc_jwks_url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=5) as response:
            jwks = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail=PROVIDER_NOT_CONFIGURED_DETAIL) from exc

    if not isinstance(jwks, dict):
        raise HTTPException(status_code=401, detail=PROVIDER_NOT_CONFIGURED_DETAIL)

    cache_ttl = max(settings.oidc_jwks_cache_seconds, 0)
    _JWKS_CACHE[settings.oidc_jwks_url] = (now + cache_ttl, jwks)
    return jwks


def _claim_as_string(claims: dict[str, Any], claim_name: str | None) -> str | None:
    if not claim_name:
        return None
    value = claims.get(claim_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _jwk_int(value: str) -> int:
    return int.from_bytes(_base64url_decode(value), "big")


def _is_active_user(user: User) -> bool:
    return _status_value(user.status) == UserStatus.ACTIVE.value


def _status_value(status: UserStatus | str) -> str:
    return status.value if isinstance(status, UserStatus) else str(status)
