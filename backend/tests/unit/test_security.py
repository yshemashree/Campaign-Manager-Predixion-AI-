import uuid

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    sign_attempt,
    verify_attempt_signature,
    verify_password,
)

S = Settings()


def test_password_hashing() -> None:
    hashed = hash_password("correct horse")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse", hashed)
    assert not verify_password("wrong", hashed)


def test_tokens_round_trip_and_reject_tampering() -> None:
    uid = uuid.uuid4()
    token = create_access_token(S, uid, "org_admin")
    claims = decode_access_token(S, token)
    assert claims["sub"] == str(uid) and claims["role"] == "org_admin"
    other = S.model_copy(update={"jwt_secret": "another-secret-that-is-long-enough-123"})
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(other, token)


def test_secrets_are_encrypted_with_a_fresh_nonce() -> None:
    a, b = encrypt_secret(S, "sk-live-123"), encrypt_secret(S, "sk-live-123")
    assert a != b and "sk-live" not in a
    assert decrypt_secret(S, a) == "sk-live-123"


def test_webhook_signature() -> None:
    sig = sign_attempt(S, "attempt-1")
    assert verify_attempt_signature(S, "attempt-1", sig)
    assert not verify_attempt_signature(S, "attempt-2", sig)
    assert not verify_attempt_signature(S, "attempt-1", "")
