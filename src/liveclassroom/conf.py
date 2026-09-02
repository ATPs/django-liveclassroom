"""Configuration defaults for host Django projects."""

from django.conf import settings

DEFAULTS = {
    "ALLOW_GUESTS": True,
    "JOIN_CODE_LENGTH": 6,
    "BASE_TEMPLATE": None,
    "DEFAULT_SESSION_MODE": "teacher_paced",
    "ALLOW_IFRAME": False,
}


def setting(name: str):
    """Return one LiveClassroom setting with a validated default."""
    if name not in DEFAULTS:
        raise KeyError(f"Unknown LiveClassroom setting: {name}")
    return getattr(settings, "LIVECLASSROOM", {}).get(name, DEFAULTS[name])
