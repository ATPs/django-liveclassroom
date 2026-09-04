"""PostgreSQL-only test settings used by the optional relay acceptance command."""

import os

from liveclassroom_test_settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("LIVECLASSROOM_POSTGRES_NAME", "liveclassroom"),
        "USER": os.environ.get("LIVECLASSROOM_POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("LIVECLASSROOM_POSTGRES_PASSWORD", "postgres"),
        "HOST": os.environ.get("LIVECLASSROOM_POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.environ.get("LIVECLASSROOM_POSTGRES_PORT", "55432"),
        "TEST": {"NAME": os.environ.get("LIVECLASSROOM_POSTGRES_TEST_NAME", "test_liveclassroom")},
    }
}
