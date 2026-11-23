"""
Settings used by the automated test-suite.

They reuse every production setting from ``base`` but swap the
infrastructure services for in-process equivalents so the suite runs
without PostgreSQL or Redis:

    DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test

Required environment variables (SECRET_KEY, DB_PASSWORD) get safe
defaults here so CI does not need a .env file.
"""

import os
import tempfile

os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-production")
os.environ.setdefault("DB_PASSWORD", "unused-in-tests")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

# Tests fire hundreds of requests per second; rate limits are tested on their own.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": (),
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# The application directory is read-only in the production container. Keep
# uploaded test fixtures in a process-owned temporary directory instead.
MEDIA_ROOT = tempfile.mkdtemp(prefix="mhtalk-test-media-")
WHITENOISE_AUTOREFRESH = True  # no collectstatic in tests
