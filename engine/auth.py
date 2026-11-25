import hashlib
import hmac
import os
import secrets
from typing import Dict

ROLE_PERMISSIONS: Dict[str, set] = {
    "admin": {"manage_users", "manage_branding", "generate_systems", "view_top_masters", "manage_clients", "delete_records", "view_schedules"},
    "locksmith": {"generate_systems", "view_top_masters", "manage_clients", "view_schedules"},
    "tech": {"manage_clients", "view_schedules"},
    "viewer": {"view_schedules"},
}

def hash_password(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}:{dk.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, dk_hex = stored_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)

def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
