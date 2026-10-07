import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "local-development-key-change-before-deployment")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///development.db")
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
    elif SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgresql://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None
    TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
    EVENT_MODE = os.getenv("EVENT_MODE", "TEST").upper()
    APP_ENV = os.getenv("APP_ENV", "development").lower()
    TEMPLATES_AUTO_RELOAD = APP_ENV != "production"
    MAX_CONTENT_LENGTH = 128 * 1024
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    AUTO_INIT_DB = os.getenv(
        "AUTO_INIT_DB", "false"
    ).lower() == "true"

    @staticmethod
    def validate_runtime():
        if os.getenv("APP_ENV", "development").lower() == "production":
            secret = os.getenv("SECRET_KEY", "")
            if len(secret) < 32 or secret.startswith(("replace-", "local-development-")):
                raise RuntimeError("Set a random SECRET_KEY of at least 32 characters in production.")
            if os.getenv("EVENT_MODE", "TEST").upper() != "PRODUCTION":
                raise RuntimeError("Set EVENT_MODE=PRODUCTION for the real event.")
            from urllib.parse import urlsplit
            public_url = urlsplit(os.getenv("PUBLIC_BASE_URL", ""))
            if public_url.scheme != "https" or not public_url.hostname:
                raise RuntimeError("Set PUBLIC_BASE_URL to the canonical HTTPS event URL.")
            if os.getenv("COOKIE_SECURE", "false").lower() != "true":
                raise RuntimeError("Set COOKIE_SECURE=true when deployed behind HTTPS.")
            if not os.getenv("DATABASE_URL", "").startswith(
                ("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")
            ):
                raise RuntimeError("Production must use PostgreSQL via DATABASE_URL.")
