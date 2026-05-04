from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi import HTTPException

from market_simulator.auth import current_user as current_user_module
from market_simulator.auth.current_user import (
    INVALID_BEARER_TOKEN_DETAIL,
    MISSING_BEARER_TOKEN_DETAIL,
    PROVIDER_NOT_CONFIGURED_DETAIL,
    USER_NOT_PROVISIONED_DETAIL,
    resolve_current_user,
)
from market_simulator.db.enums import UserStatus
from market_simulator.db.models.user import UserExternalIdentity
from market_simulator.settings import Settings


DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
OIDC_ISSUER = "https://issuer.example.test"
OIDC_AUDIENCE = "market-simulator-api"
OIDC_JWKS_URL = "https://issuer.example.test/.well-known/jwks.json"
TEST_KEY_ID = "test-key-1"
TEST_RSA_N = (
    "qlDd2mOketJVpsW_Ikl8OlAsI3085tHw1qyX0xSfmE2nYv9m34DVQzWtHqd-q7erIiDSy1ifb4vXeYel"
    "6AroE8qdtriKk2zBDOZ81wKScWdAYii5-LF0AbG7iKlkE4C2x-daWpdlc474mKaghQ8-oII_SnR4MqfWm"
    "n7KLynk1b7gjOTEPDwmAD7z9ALYOOlRZ4BpEwqLbfiiXv2MyFtz-Ta_ZTrqZWkK9aWut3ZAn9qtacVNl"
    "cDVsbPbRItKdk_RwSbBB87mS7L0bAdQLrZwkIVrgEik8k17MNYqoy7PZnfpjnoowSYWSx0PsCMXj-6xF"
    "am-fH76WB2fFMxFtw3LKQ"
)
TEST_RSA_E = "AQAB"
TEST_RSA_D = (
    "AefIZDoe6-qJLmNYWWoyNAT2Iq8LlBwc78WW7MeAU0avIIZKQyY-LcdZrr1N-JmaPX2K5stpXsGGaLeK"
    "g6ij4rqk1tKYP4WYwtglvchcsvp57fVa6grZ4aozotzh-HgxmDg-a81EL8szGmdTIRn1IvwuWtrsy1Nc"
    "rSdrIUJVOfE8xIIKjj50ceVc8Va7Cgfq8Dd148uo3n_rTiiLwbCiClQwC_dmzi4DNIbO3h6_fyXVh5mc"
    "avFEVFA0LrFwPN5Hcoj9Uosd6JO1rdLTnxN0EbZbRFpWeTfAhHJBHW7k8sdQ5xIdzt4XWQGe1aVnN5K"
    "lyconrLQlOyQLx-4DNknbpw"
)
SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


def _assert_auth_error(exc_info, *, status_code: int, detail: str) -> None:
    exc = exc_info.value
    assert exc.status_code == status_code
    assert exc.detail == detail


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _json_b64url(value: dict) -> str:
    return _b64url_encode(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())


def _test_jwks() -> dict:
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": TEST_KEY_ID,
                "use": "sig",
                "alg": "RS256",
                "n": TEST_RSA_N,
                "e": TEST_RSA_E,
            }
        ]
    }


def _mock_jwks(monkeypatch) -> None:
    monkeypatch.setattr(current_user_module, "_get_jwks", lambda _settings: _test_jwks())


def _oidc_settings(**overrides) -> Settings:
    values = {
        "env": "beta",
        "auth_mode": "oidc",
        "oidc_issuer": OIDC_ISSUER,
        "oidc_audience": OIDC_AUDIENCE,
        "oidc_jwks_url": OIDC_JWKS_URL,
        "dev_default_user_id": DEV_USER_ID,
    }
    values.update(overrides)
    return Settings(**values)


def _signed_test_jwt(**claim_overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": OIDC_ISSUER,
        "aud": OIDC_AUDIENCE,
        "sub": "oidc-subject-123",
        "email": "oidc-user@example.com",
        "name": "OIDC User",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    claims.update(claim_overrides)

    header = {"alg": "RS256", "kid": TEST_KEY_ID, "typ": "JWT"}
    signing_input = f"{_json_b64url(header)}.{_json_b64url(claims)}".encode("ascii")

    modulus = int.from_bytes(_b64url_decode(TEST_RSA_N), "big")
    private_exponent = int.from_bytes(_b64url_decode(TEST_RSA_D), "big")
    key_size_bytes = (modulus.bit_length() + 7) // 8
    digest_info = SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(signing_input).digest()
    padding = b"\xff" * (key_size_bytes - len(digest_info) - 3)
    encoded_message = b"\x00\x01" + padding + b"\x00" + digest_info
    signature = pow(
        int.from_bytes(encoded_message, "big"),
        private_exponent,
        modulus,
    ).to_bytes(key_size_bytes, "big")

    return f"{signing_input.decode('ascii')}.{_b64url_encode(signature)}"


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
            settings=Settings(
                env="local",
                auth_mode="required",
                dev_default_user_id=DEV_USER_ID,
                oidc_jwks_url=None,
            ),
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
                settings=Settings(
                    env=env,
                    auth_mode="dev",
                    dev_default_user_id=DEV_USER_ID,
                    oidc_jwks_url=None,
                ),
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
                settings=Settings(
                    env=env,
                    auth_mode="required",
                    dev_default_user_id=DEV_USER_ID,
                    oidc_jwks_url=None,
                ),
            )

        _assert_auth_error(
            exc_info,
            status_code=401,
            detail=PROVIDER_NOT_CONFIGURED_DETAIL,
        )


def test_oidc_mode_rejects_missing_authorization(db_session, monkeypatch):
    _mock_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(db=db_session, settings=_oidc_settings())

    _assert_auth_error(exc_info, status_code=401, detail=MISSING_BEARER_TOKEN_DETAIL)


def test_oidc_mode_rejects_malformed_authorization(db_session, monkeypatch):
    _mock_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(),
            authorization="Token abc.def.ghi",
        )

    _assert_auth_error(exc_info, status_code=401, detail="Malformed Authorization header")


def test_oidc_mode_rejects_invalid_token(db_session, monkeypatch):
    _mock_jwks(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(),
            authorization="Bearer not-a-jwt",
        )

    _assert_auth_error(exc_info, status_code=401, detail=INVALID_BEARER_TOKEN_DETAIL)


def test_oidc_mode_maps_valid_signed_jwt_by_provider_subject(
    db_session,
    create_user,
    monkeypatch,
):
    _mock_jwks(monkeypatch)
    user = create_user(email="linked-user@example.com", display_name="Database Name")
    db_session.add(
        UserExternalIdentity(
            user_id=user.id,
            provider="oidc",
            subject="oidc-subject-123",
            email_at_link_time="old-email@example.com",
        )
    )
    db_session.commit()
    token = _signed_test_jwt(email=None)

    current_user = resolve_current_user(
        db=db_session,
        settings=_oidc_settings(),
        authorization=f"Bearer {token}",
        x_user_id=str(uuid.uuid4()),
    )

    assert current_user.id == str(user.id)
    assert current_user.email == "linked-user@example.com"
    assert current_user.display_name == "Database Name"


def test_oidc_mode_links_existing_email_user_when_email_linking_enabled(
    db_session,
    create_user,
    monkeypatch,
):
    _mock_jwks(monkeypatch)
    user = create_user(email="oidc-user@example.com")
    token = _signed_test_jwt()

    current_user = resolve_current_user(
        db=db_session,
        settings=_oidc_settings(),
        authorization=f"Bearer {token}",
    )

    identity = db_session.query(UserExternalIdentity).one()
    assert current_user.id == str(user.id)
    assert identity.user_id == user.id
    assert identity.provider == "oidc"
    assert identity.subject == "oidc-subject-123"
    assert identity.email_at_link_time == "oidc-user@example.com"


def test_oidc_mode_rejects_email_fallback_when_linking_disabled(
    db_session,
    create_user,
    monkeypatch,
):
    _mock_jwks(monkeypatch)
    create_user(email="oidc-user@example.com")
    token = _signed_test_jwt()

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(oidc_allow_email_linking=False),
            authorization=f"Bearer {token}",
        )

    _assert_auth_error(
        exc_info,
        status_code=401,
        detail=USER_NOT_PROVISIONED_DETAIL,
    )
    assert db_session.query(UserExternalIdentity).count() == 0


def test_oidc_mode_uses_required_auth_mode_when_jwks_is_configured(
    db_session,
    create_user,
    monkeypatch,
):
    _mock_jwks(monkeypatch)
    user = create_user(email="oidc-user@example.com")
    token = _signed_test_jwt()

    current_user = resolve_current_user(
        db=db_session,
        settings=_oidc_settings(auth_mode="required"),
        authorization=f"Bearer {token}",
    )

    assert current_user.id == str(user.id)


def test_oidc_mode_rejects_unprovisioned_email(db_session, monkeypatch):
    _mock_jwks(monkeypatch)
    token = _signed_test_jwt(email="missing@example.com")

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(),
            authorization=f"Bearer {token}",
        )

    _assert_auth_error(
        exc_info,
        status_code=401,
        detail=USER_NOT_PROVISIONED_DETAIL,
    )


def test_oidc_mode_rejects_inactive_linked_user(db_session, create_user, monkeypatch):
    _mock_jwks(monkeypatch)
    user = create_user(email="oidc-user@example.com")
    user.status = UserStatus.SUSPENDED
    db_session.add(
        UserExternalIdentity(
            user_id=user.id,
            provider="oidc",
            subject="oidc-subject-123",
            email_at_link_time="oidc-user@example.com",
        )
    )
    db_session.commit()
    token = _signed_test_jwt()

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(),
            authorization=f"Bearer {token}",
        )

    _assert_auth_error(exc_info, status_code=403, detail="User is not active")


def test_oidc_mode_rejects_wrong_audience_or_issuer(db_session, create_user, monkeypatch):
    _mock_jwks(monkeypatch)
    create_user(email="oidc-user@example.com")

    for token in (
        _signed_test_jwt(aud="other-api"),
        _signed_test_jwt(iss="https://other-issuer.example.test"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            resolve_current_user(
                db=db_session,
                settings=_oidc_settings(),
                authorization=f"Bearer {token}",
            )

        _assert_auth_error(exc_info, status_code=401, detail=INVALID_BEARER_TOKEN_DETAIL)


def test_oidc_mode_rejects_expired_token(db_session, create_user, monkeypatch):
    _mock_jwks(monkeypatch)
    create_user(email="oidc-user@example.com")
    token = _signed_test_jwt(
        exp=int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    )

    with pytest.raises(HTTPException) as exc_info:
        resolve_current_user(
            db=db_session,
            settings=_oidc_settings(),
            authorization=f"Bearer {token}",
        )

    _assert_auth_error(exc_info, status_code=401, detail="Token is expired")
