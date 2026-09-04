"""Configuration defaults for host Django projects."""

from django.conf import settings

DEFAULTS = {
    "ALLOW_GUESTS": True,
    "JOIN_CODE_LENGTH": 6,
    "BASE_TEMPLATE": None,
    "ALLOW_IFRAME": False,
    "WEBSOCKET_PATH": "/ws/liveclassroom/sessions/{session_id}/",
    "RETENTION_DAYS": None,
    "CONTENT_PROVIDERS": {},
    "AI_BACKENDS": {},
    "AI_JOB_DISPATCHER": None,
    "AI_JOB_MAX_ATTEMPTS": 3,
    "AI_JOB_TIMEOUT_SECONDS": 300,
    "ASSET_MAX_BYTES": 50 * 1024 * 1024,
    "ALLOW_SERVER_FILE_PATHS": False,
}


def setting(name: str):
    """Return one LiveClassroom setting with a validated default."""
    if name not in DEFAULTS:
        raise KeyError(f"Unknown LiveClassroom setting: {name}")
    configured = getattr(settings, "LIVECLASSROOM", {})
    if not isinstance(configured, dict):
        raise ValueError("LIVECLASSROOM must be a mapping.")
    return configured.get(name, DEFAULTS[name])


def join_code_length() -> int:
    """Return the configured join-code length within the model's safe bounds."""
    length = setting("JOIN_CODE_LENGTH")
    if isinstance(length, bool) or not isinstance(length, int) or not 4 <= length <= 12:
        raise ValueError("LIVECLASSROOM['JOIN_CODE_LENGTH'] must be an integer from 4 to 12.")
    return length


def base_template() -> str:
    """Return the host layout template or the packaged standalone layout."""
    template = setting("BASE_TEMPLATE")
    if template is None:
        return "liveclassroom/base.html"
    if not isinstance(template, str) or not template.strip():
        raise ValueError("LIVECLASSROOM['BASE_TEMPLATE'] must be a non-empty template path or None.")
    return template.strip()


def guests_allowed() -> bool:
    """Return whether this host permits guest classroom entry."""
    allowed = setting("ALLOW_GUESTS")
    if not isinstance(allowed, bool):
        raise ValueError("LIVECLASSROOM['ALLOW_GUESTS'] must be a boolean.")
    return allowed


def websocket_path(session_id: int) -> str:
    """Build the host-configured WebSocket path for one session."""
    template = setting("WEBSOCKET_PATH")
    if not isinstance(template, str) or "{session_id}" not in template:
        raise ValueError("LIVECLASSROOM['WEBSOCKET_PATH'] must contain {session_id}.")
    return template.format(session_id=int(session_id))


def ai_job_max_attempts() -> int:
    attempts = setting("AI_JOB_MAX_ATTEMPTS")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10:
        raise ValueError("LIVECLASSROOM['AI_JOB_MAX_ATTEMPTS'] must be an integer from 1 to 10.")
    return attempts


def ai_job_timeout_seconds() -> int:
    timeout = setting("AI_JOB_TIMEOUT_SECONDS")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 3600:
        raise ValueError("LIVECLASSROOM['AI_JOB_TIMEOUT_SECONDS'] must be an integer from 10 to 3600.")
    return timeout


def asset_max_bytes() -> int:
    value = setting("ASSET_MAX_BYTES")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("LIVECLASSROOM['ASSET_MAX_BYTES'] must be a positive integer.")
    return value


def server_file_paths_allowed() -> bool:
    value = setting("ALLOW_SERVER_FILE_PATHS")
    if not isinstance(value, bool):
        raise ValueError("LIVECLASSROOM['ALLOW_SERVER_FILE_PATHS'] must be a boolean.")
    return value
