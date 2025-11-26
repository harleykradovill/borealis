import sqlite3
import logging
import os

logger = logging.getLogger("finbot.web.db")

def _db_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "finbot.db"))

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
            config[key] = value
    return config

def set_config_items(items: dict):
    if not items:
        return
    
    path = _db_path()
    with sqlite3.connect(path) as conn:
        for key, value in items.items():
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, str(value))
            )
        conn.commit()
    logger.info("Updated config keys: %s", ", ".join(items.keys()))

def migrate_from_env(env_path: str):
    if not os.path.exists(env_path):
        logger.warning("Env file %s not found, skipping migration", env_path)
        return
    
    try:
        from dotenv import dotenv_values
        values = dotenv_values(env_path)
        if values:
            set_config_items(values)
            logger.info("Migrated %d keys from %s to SQLite", len(values), env_path)
        else:
            logger.info("No values found in %s", env_path)
    except ImportError:
        logger.warning("dotenv not available, cannot migrate from env file")