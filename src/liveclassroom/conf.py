"""Configuration defaults for host Django projects."""

from django.conf import settings

DEFAULTS = {
    "ALLOW_GUESTS": True,
    "JOIN_CODE_LENGTH": 6,
    "BASE_TEMPLATE": None,
    "DEFAULT_SESSION_MODE": "teacher_paced",
    "ALLOW_IFRAME": False,
    "WEBSOCKET_PATH": "/ws/liveclassroom/sessions/{session_id}/",
    "RETENTION_DAYS": None,
    "AI_BACKENDS": {},
    "AI_JOB_DISPATCHER": None,
}


def setting(name: str):
    """Return one LiveClassroom setting with a validated default."""
    if name not in DEFAULTS:
        raise KeyError(f"Unknown LiveClassroom setting: {name}")
    return getattr(settings, "LIVECLASSROOM", {}).get(name, DEFAULTS[name])


def websocket_path(session_id: int) -> str:
    """Build the host-configured WebSocket path for one session."""
    template = setting("WEBSOCKET_PATH")
    if not isinstance(template, str) or "{session_id}" not in template:
        raise ValueError("LIVECLASSROOM['WEBSOCKET_PATH'] must contain {session_id}.")
    return template.format(session_id=int(session_id))
