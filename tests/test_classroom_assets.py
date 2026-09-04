import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import ClassroomAsset, Flow, SessionChannelState
from liveclassroom.services.classroom import create_instant_session, join_guest, start_session


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def response_bytes(response):
    return b"".join(response.streaming_content)


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user(username="asset-teacher", password="secret")


@pytest.fixture
def teacher_client(teacher):
    client = Client()
    client.force_login(teacher)
    return client


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/liveclassroom-test-media")
def test_flow_markdown_upload_creates_revisioned_private_asset(teacher, teacher_client):
    flow = Flow.objects.create(title="File flow", created_by=teacher)
    response = teacher_client.post(
        reverse("liveclassroom:api-v1-flow-files", args=[flow.id]),
        data={
            "title": "Lecture notes",
            "caption": "Week one",
            "file": SimpleUploadedFile("notes.md", b"# Welcome\n", content_type="text/markdown"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    asset = ClassroomAsset.objects.get(public_id=payload["asset"]["id"])
    step = flow.steps.get(pk=payload["step"]["id"])
    assert asset.source == ClassroomAsset.Source.UPLOAD
    assert step.activity_definition.asset_id == asset.id
    assert step.activity_definition.current_revision.asset_id == asset.id

    content = teacher_client.get(payload["asset"]["content_url"])
    assert content.status_code == 200
    assert response_bytes(content) == b"# Welcome\n"
    assert content["Content-Disposition"].startswith("inline;")


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/liveclassroom-test-media")
def test_session_file_limits_student_delivery_to_published_revision(teacher, teacher_client):
    session = create_instant_session(owner=teacher, title="Files in class")
    start_session(session=session, actor=teacher)
    response = teacher_client.post(
        reverse("liveclassroom:api-v1-session-files", args=[session.id]),
        data={
            "title": "Shared notes",
            "channels": json.dumps(["display", "participants"]),
            "file": SimpleUploadedFile("shared.md", b"# Shared\n"),
        },
    )
    assert response.status_code == 201

    display_state = teacher_client.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "display"}
    ).json()
    display_asset = display_state["current_activity"]["definition"]["content"]["asset"]
    assert display_asset["download_url"].endswith("?download=1")

    participant = join_guest(session=session, display_name="Student")
    student = Client()
    browser_session = student.session
    browser_session[f"liveclassroom.participant.{session.id}"] = participant.id
    browser_session.save()
    student_state = student.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "participants"}
    ).json()
    student_asset = student_state["current_activity"]["definition"]["content"]["asset"]
    assert "download_url" not in student_asset

    content = student.get(student_asset["content_url"])
    assert content.status_code == 200
    assert response_bytes(content) == b"# Shared\n"
    assert student.get(f'{student_asset["content_url"]}?download=1').status_code == 403

    SessionChannelState.objects.filter(session=session, channel="participants").update(current_revision=None)
    assert student.get(student_asset["content_url"]).status_code == 404


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/liveclassroom-test-media")
def test_video_asset_supports_single_byte_ranges(teacher, teacher_client):
    session = create_instant_session(owner=teacher, title="Video range")
    start_session(session=session, actor=teacher)
    video = b"\x1aE\xdf\xa3" + (b"x" * 24)
    response = teacher_client.post(
        reverse("liveclassroom:api-v1-session-files", args=[session.id]),
        data={"channels": json.dumps(["participants"]), "file": SimpleUploadedFile("clip.webm", video)},
    )
    assert response.status_code == 201
    activity_id = response.json()["activity_id"]
    state = teacher_client.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "participants"}
    ).json()
    url = state["current_activity"]["definition"]["content"]["asset"]["content_url"]

    ranged = teacher_client.get(url, HTTP_RANGE="bytes=3-8")
    assert ranged.status_code == 206
    assert response_bytes(ranged) == video[3:9]
    assert ranged["Content-Range"] == f"bytes 3-8/{len(video)}"
    assert ranged["Accept-Ranges"] == "bytes"
    assert teacher_client.get(url, HTTP_RANGE="bytes=999-").status_code == 416
    assert activity_id


@pytest.mark.django_db
@override_settings(MEDIA_ROOT="/tmp/liveclassroom-test-media")
def test_presentation_state_requires_active_file_and_updates_channels(teacher, teacher_client):
    session = create_instant_session(owner=teacher, title="Paged file")
    start_session(session=session, actor=teacher)
    upload = teacher_client.post(
        reverse("liveclassroom:api-v1-session-files", args=[session.id]),
        data={
            "channels": json.dumps(["display", "participants"]),
            "file": SimpleUploadedFile("slides.md", b"# Page one"),
        },
    )
    assert upload.status_code == 201

    session.refresh_from_db(fields=["state_version"])
    previous_version = session.state_version
    updated = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-session-presentation", args=[session.id]),
        {"channels": ["display", "participants"], "page": 3, "navigation_mode": "paged"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == previous_version + 1
    state = teacher_client.get(
        reverse("liveclassroom:api-v1-state", args=[session.id]), {"channel": "display"}
    ).json()
    assert state["channels"]["display"]["presentation"] == {"page": 3, "navigation_mode": "follow"}
    assert state["channels"]["participants"]["presentation"] == {"page": 3, "navigation_mode": "paged"}


@pytest.mark.django_db
def test_file_validation_and_live_server_reference(teacher, teacher_client, tmp_path):
    flow = Flow.objects.create(title="Server file flow", created_by=teacher)
    invalid = teacher_client.post(
        reverse("liveclassroom:api-v1-flow-files", args=[flow.id]),
        data={"file": SimpleUploadedFile("not-a-pdf.pdf", b"not a PDF")},
    )
    assert invalid.status_code == 400
    assert ClassroomAsset.objects.count() == 0

    path = tmp_path / "remote.md"
    path.write_bytes(b"# First version\n")
    teacher.is_superuser = True
    teacher.save(update_fields=["is_superuser"])
    with override_settings(LIVECLASSROOM={"ALLOW_SERVER_FILE_PATHS": True}):
        response = post_json(
            teacher_client,
            reverse("liveclassroom:api-v1-flow-files", args=[flow.id]),
            {"server_path": str(path)},
        )
        assert response.status_code == 201
        content_url = response.json()["asset"]["content_url"]
        first = teacher_client.get(content_url)
        assert response_bytes(first) == b"# First version\n"
        path.write_bytes(b"# Current version\n")
        current = teacher_client.get(content_url)
        assert current.status_code == 200
        assert response_bytes(current) == b"# Current version\n"


@pytest.mark.django_db
def test_server_reference_requires_enabled_superuser(teacher, teacher_client, tmp_path):
    flow = Flow.objects.create(title="Restricted server file", created_by=teacher)
    path = tmp_path / "notes.md"
    path.write_bytes(b"# Private")
    response = post_json(
        teacher_client,
        reverse("liveclassroom:api-v1-flow-files", args=[flow.id]),
        {"server_path": str(path)},
    )
    assert response.status_code == 400
    assert ClassroomAsset.objects.count() == 0
