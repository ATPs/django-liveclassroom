import pytest
from django.contrib.auth import get_user_model
from django.core.checks import Tags, run_checks
from django.test import override_settings
from django.urls import reverse

from liveclassroom.conf import join_code_length
from liveclassroom.models import LiveSession
from liveclassroom.services.classroom import ClassroomError, create_instant_session, join_guest, start_session


@pytest.mark.django_db
@override_settings(LIVECLASSROOM={"JOIN_CODE_LENGTH": 8, "DEFAULT_SESSION_MODE": "student_paced"})
def test_session_defaults_and_join_code_length_follow_host_configuration():
    teacher = get_user_model().objects.create_user(username="configured-teacher")
    session = create_instant_session(owner=teacher, title="Configured classroom")

    assert join_code_length() == 8
    assert len(session.join_code) == 8
    assert session.mode == LiveSession.Mode.STUDENT_PACED


@pytest.mark.django_db
@override_settings(LIVECLASSROOM={"ALLOW_GUESTS": False})
def test_host_can_disable_guest_session_creation_and_entry():
    teacher = get_user_model().objects.create_user(username="guest-disabled-teacher")
    session = create_instant_session(owner=teacher, title="Authenticated only")

    assert session.access_mode == LiveSession.AccessMode.AUTHENTICATED
    with pytest.raises(ClassroomError, match="Guest classroom entry is disabled"):
        create_instant_session(
            owner=teacher,
            title="Invalid guest session",
            access_mode=LiveSession.AccessMode.GUEST,
        )

    session.access_mode = LiveSession.AccessMode.BOTH
    session.save(update_fields=["access_mode"])
    start_session(session=session, actor=teacher)
    with pytest.raises(ClassroomError, match="Guest classroom entry is disabled"):
        join_guest(session=session, display_name="Ada")


@override_settings(
    LIVECLASSROOM={"BASE_TEMPLATE": "host_base.html"},
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": ["django.template.context_processors.request"],
                "loaders": [
                    (
                        "django.template.loaders.locmem.Loader",
                        {"host_base.html": "<html><body>host-layout:{% block content %}{% endblock %}</body></html>"},
                    ),
                    "django.template.loaders.app_directories.Loader",
                ],
            },
        }
    ],
)
def test_host_base_template_wraps_liveclassroom_pages(client):
    response = client.get(reverse("liveclassroom:home"))

    assert response.status_code == 200
    assert b"host-layout:" in response.content
    assert b"LiveClassroom" in response.content


@override_settings(LIVECLASSROOM={"JOIN_CODE_LENGTH": 3})
def test_system_check_rejects_invalid_configuration_values():
    messages = run_checks(tags=[Tags.compatibility])

    assert any(message.id == "liveclassroom.E004" for message in messages)


@override_settings(LIVECLASSROOM={"AI_BACKENDS": {"broken": object()}, "CONTENT_PROVIDERS": {"broken": object()}})
def test_system_check_rejects_incomplete_host_extension_objects():
    messages = run_checks(tags=[Tags.compatibility])
    identifiers = {message.id for message in messages}

    assert "liveclassroom.E005" in identifiers
    assert "liveclassroom.E006" in identifiers
