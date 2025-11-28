import sqlite3
import logging
import os
import contextlib
from typing import Optional

logger = logging.getLogger("finbot.web.db")

try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_AVAILABLE = True
except Exception:
    Fernet = None
    InvalidToken = Exception
    _CRYPTO_AVAILABLE = False

_SECRET_KEYS = {"DISCORD_TOKEN", "JELLYFIN_API_KEY"}
_ENC_PREFIX = "enc:"

def _key_path() -> str:
    return os.path.join(os.path.dirname(__file__), "secret.key")

def _ensure_key_file() -> Optional[bytes]:
    if not _CRYPTO_AVAILABLE:
        logger.warning("cryptography not installed; secrets will be plaintext")
        return None

    path = _key_path()
    if not os.path.exists(path):
        try:
            key = Fernet.generate_key()
            with open(path, "wb") as f:
                f.write(key)
            with contextlib.suppress(Exception):
                os.chmod(path, 0o600)
        except Exception as e:
            logger.warning("Failed to create key file: %s", e)
            return None

    try:
        with open(path, "rb") as f:
            return f.read().strip()
    except Exception as e:
        logger.warning("Failed to read key file: %s", e)
        return None

def _get_fernet() -> Optional["Fernet"]:
    key = _ensure_key_file()
    if not key or not _CRYPTO_AVAILABLE:
        return None
    try:
        return Fernet(key)
    except Exception as e:
        logger.warning("Invalid encryption key; secrets left plaintext: %s", e)
        return None

def _encrypt_value(plain: str) -> str:
    f = _get_fernet()
    if not f:
        return plain
    try:
        token = f.encrypt(plain.encode("utf-8"))
        return f"{_ENC_PREFIX}{token.decode('utf-8')}"
    except Exception as e:
        logger.warning("Encrypt failed; storing plaintext: %s", e)
        return plain

def _decrypt_value(value: str) -> str:
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    f = _get_fernet()
    if not f:
        logger.warning("Encrypted secret present but crypto unavailable.")
        return ""
    try:
        token = value[len(_ENC_PREFIX):].encode("utf-8")
        return f.decrypt(token).decode("utf-8")
    except InvalidToken:
        logger.warning("Secret decryption failed: invalid token.")
        return ""
    except Exception as e:
        logger.warning("Secret decryption error: %s", e)
        return ""

def _db_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "../finbot.db"))

def init_db():
    path = _db_path()
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.commit()
    logger.info("Database initialized at %s", path)

def get_all_config():
    path = _db_path()
    config = {}
    with sqlite3.connect(path) as conn:
        cursor = conn.execute("SELECT key, value FROM config")
        for key, value in cursor.fetchall():
            config[key] = _decrypt_value(value)
    return config

def set_config_items(items: dict):
    if not items:
        return

    path = _db_path()
    with sqlite3.connect(path) as conn:
        for key, value in items.items():
            val_str = str(value)
            if key in _SECRET_KEYS and not val_str.startswith(_ENC_PREFIX):
                val_str = _encrypt_value(val_str)
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, val_str),
            )
        conn.commit()
    logger.info("Updated config keys: %s", ", ".join(items.keys()))