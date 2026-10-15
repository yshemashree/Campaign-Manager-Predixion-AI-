"""Passwords, login tokens, secret encryption and webhook signatures."""

import base64
import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

_hasher = PasswordHasher()  # argon2id with library defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(settings: Settings, user_id: uuid.UUID, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError if the token is invalid or expired."""
    decoded: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    return decoded


def _aes_key(settings: Settings) -> bytes:
    key = base64.b64decode(settings.encryption_key)
    if len(key) != 32:
        raise ValueError("ENCRYPTION_KEY must be 32 bytes, base64 encoded")
    return key


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    """AES-256-GCM. Output is base64(nonce + ciphertext), safe to store in a text column."""
    nonce = os.urandom(12)
    ciphertext = AESGCM(_aes_key(settings)).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()


def decrypt_secret(settings: Settings, token: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_aes_key(settings)).decrypt(raw[:12], raw[12:], None).decode()


def sign_attempt(settings: Settings, attempt_ref: str) -> str:
    """Signature we put in the webhook metadata, so we can trust the webhook that echoes it."""
    return hmac.new(
        settings.webhook_signing_secret.encode(), attempt_ref.encode(), hashlib.sha256
    ).hexdigest()


def verify_attempt_signature(settings: Settings, attempt_ref: str, signature: str) -> bool:
    return hmac.compare_digest(sign_attempt(settings, attempt_ref), signature)
