"""Test settings on a real PostgreSQL server.

The default SQLite test settings cannot exercise concurrent writers: shared-cache
SQLite answers a second writer with "database table is locked" before the unique
constraint can refuse a raced duplicate transfer. Run the settlement concurrency
test against PostgreSQL with:

    TEST_DATABASE_URL=postgres://mhtalk:mhtalk@127.0.0.1:5432/mhtalk_test \\
    DJANGO_SETTINGS_MODULE=config.settings.test_postgres \\
    python manage.py test apps.marketplace

Falls back to DATABASE_URL, then to the local Docker defaults below.
"""

import os

# test.py first: it seeds the SECRET_KEY/DB_PASSWORD defaults base.py requires.
from .test import *  # noqa: E402,F401,F403
from .base import _database_from_url  # noqa: E402

_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or ""
if _url.startswith(("postgres://", "postgresql://")):
    DATABASES = {"default": _database_from_url(_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("TEST_DB_NAME", "mhtalk_test"),
            "USER": os.environ.get("TEST_DB_USER", "mhtalk"),
            "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "mhtalk"),
            "HOST": os.environ.get("TEST_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("TEST_DB_PORT", "5433"),
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": True,
        }
    }
