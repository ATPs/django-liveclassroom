import os
import tempfile

SECRET_KEY = "test-key"
DEBUG = True
MEDIA_ROOT = "/tmp/liveclassroom-test-media"
ROOT_URLCONF = "liveclassroom_test_urls"
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "channels",
    "liveclassroom",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(tempfile.gettempdir(), f"liveclassroom-checks-{os.getpid()}.sqlite3"),
        # LiveServer handles parallel browser requests. A file keeps each thread
        # on its own connection instead of sharing the in-memory test connection.
        # Both names must be files: the session-scoped server may start before
        # pytest-django has switched the connection to the test database.
        "TEST": {"NAME": os.path.join(tempfile.gettempdir(), f"liveclassroom-tests-{os.getpid()}.sqlite3")},
        "OPTIONS": {"timeout": 30},
    }
}
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
STATIC_URL = "/static/"
