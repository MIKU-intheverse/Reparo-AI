import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings

settings = get_settings()


def _derive_key() -> bytes:
    """
    Fernet needs a 32-byte urlsafe-base64 key. If ENCRYPTION_KEY is set, use
    it directly (it must already be a valid Fernet key — generate one with
    `Fernet.generate_key()`). Otherwise derive a *deterministic* key from
    AUTH_SECRET so local dev works out of the box. This fallback must NOT be
    used in any deployed/production environment — set ENCRYPTION_KEY there.
    """
    if settings.encryption_key:
        return settings.encryption_key.encode()
    digest = hashlib.sha256(settings.auth_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt_secret(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()


def mask_key_id(key_id: str) -> str:
    if len(key_id) <= 8:
        return "****"
    return f"{key_id[:8]}{'*' * (len(key_id) - 12)}{key_id[-4:]}"
