import json
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import ActivityRunRevision, ClassroomAsset
from liveclassroom.services.classroom import create_instant_session, join_guest, start_session


@pytest.fixture
def vaultpub_apps():
    with override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "vaultpub.django_app"]):
        yield


def _uploaded_markdown(client, *, session_id=None):
    url = (
        reverse("liveclassroom:api-v1-session-files", args=[session_id])
        if session_id
        else reverse("liveclassroom:api-v1-flows")
    )
    if session_id:
        response = client.post(
            url,
            data={
                "channels": json.dumps(["participants"]),
                "file": SimpleUploadedFile("Deck.md", b"# First\n\n---\n\n# Second\n"),
            },
        )
        assert response.status_code == 201
        return ClassroomAsset.objects.get(public_id=response.json()["asset"]["id"])
    raise AssertionError("session_id is required")


@pytest.mark.django_db
def test_uploaded_document_routes_are_scoped_mount_safe_and_private(vaultpub_apps, tmp_path):
    teacher = get_user_model().objects.create_user(username="document-owner")
    other = get_user_model().objects.create_user(username="document-other")
    session = create_instant_session(owner=teacher, title="Document routes")
    start_session(session=session, actor=teacher)
    client = Client()
    client.force_login(teacher)
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _uploaded_markdown(client, session_id=session.id)

        root = reverse("liveclassroom:api-v1-document-root", args=[asset.public_id])
        note = client.get(root)
        assert note.status_code == 200
        assert note["Cache-Control"] == "private, no-store"
        assert note["X-Frame-Options"] == "SAMEORIGIN"
        assert str(tmp_path) not in note.content.decode()
        assert f"{root}__slides__/Deck.md" in note.content.decode()

        exact = client.get(reverse("liveclassroom:api-v1-document-note", args=[asset.public_id, "Deck.md"]))
        slides = client.get(
            reverse("liveclassroom:api-v1-document-slides", args=[asset.public_id, "Deck.md"]),
            {"embed": "1"},
        )
        payload = client.get(
            reverse("liveclassroom:api-v1-document-slides-payload", args=[asset.public_id, "Deck.md"])
        )
        assert exact.status_code == slides.status_code == payload.status_code == 200
        assert "data-vaultpub-embed=\"true\"" in slides.content.decode()
        assert len(payload.json()["slides"]) == 2
        wrong_note = reverse("liveclassroom:api-v1-document-note", args=[asset.public_id, "Other.md"])
        missing_image = reverse("liveclassroom:api-v1-document-resource", args=[asset.public_id, "image.png"])
        assert client.get(wrong_note).status_code == 404
        assert client.get(missing_image).status_code == 404
        assert client.post(root).status_code == 405
        assert client.head(root).status_code == 200

        denied = Client()
        denied.force_login(other)
        assert denied.get(root).status_code == 404
        assert Client().get(root).status_code == 404

        with override_settings(ROOT_URLCONF="tests.mounted_urls"):
            mounted = reverse("liveclassroom:api-v1-document-root", args=[asset.public_id])
            assert mounted.startswith("/classroom/")
            mounted_response = client.get(mounted)
            assert mounted_response.status_code == 200
            assert mounted in mounted_response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_server_document_serves_only_referenced_direct_sibling(vaultpub_apps, tmp_path):
    teacher = get_user_model().objects.create_user(username="server-document", is_superuser=True)
    note = tmp_path / "Server.md"
    note.write_text("# Server\n\n![ok](allowed.png)\n", encoding="utf-8")
    (tmp_path / "allowed.png").write_bytes(b"allowed")
    (tmp_path / "private.png").write_bytes(b"private")
    (tmp_path / "Other.md").write_text("# Private", encoding="utf-8")
    asset = ClassroomAsset.objects.create(
        owner=teacher,
        source=ClassroomAsset.Source.SERVER_PATH,
        server_path=str(note),
        original_name=note.name,
        kind=ClassroomAsset.Kind.MARKDOWN,
        content_type="text/markdown; charset=utf-8",
        byte_size=note.stat().st_size,
    )
    client = Client()
    client.force_login(teacher)
    allowed = client.get(
        reverse("liveclassroom:api-v1-document-resource", args=[asset.public_id, "allowed.png"])
    )
    try:
        assert allowed.status_code == 200
        assert b"".join(allowed.streaming_content) == b"allowed"
    finally:
        allowed.close()
    for resource in ("private.png", "Other.md", "nested/image.png", "../allowed.png"):
        assert client.get(
            reverse("liveclassroom:api-v1-document-resource", args=[asset.public_id, resource])
        ).status_code == 404


@pytest.mark.django_db
def test_session_document_reauthorizes_exact_current_revision(vaultpub_apps, tmp_path):
    teacher = get_user_model().objects.create_user(username="session-document")
    session = create_instant_session(owner=teacher, title="Published document")
    start_session(session=session, actor=teacher)
    teacher_client = Client()
    teacher_client.force_login(teacher)
    with override_settings(MEDIA_ROOT=tmp_path):
        asset = _uploaded_markdown(teacher_client, session_id=session.id)
        revision = ActivityRunRevision.objects.get(activity__session=session, asset=asset)
        participant = join_guest(session=session, display_name="Reader")
        student = Client()
        browser_session = student.session
        browser_session[f"liveclassroom.participant.{session.id}"] = participant.id
        browser_session.save()
        url = reverse(
            "liveclassroom:api-v1-session-document-root",
            args=[session.id, revision.id, asset.public_id],
        )
        assert student.get(url).status_code == 200
        assert teacher_client.get(url).status_code == 200
        assert student.get(
            reverse(
                "liveclassroom:api-v1-session-document-root",
                args=[session.id, revision.id + 1000, asset.public_id],
            )
        ).status_code == 404
        session.channel_states.filter(channel="participants").update(show_prompt=False)
        assert student.get(url).status_code == 404


@pytest.mark.django_db
def test_document_routes_report_missing_vaultpub_app_without_path(tmp_path):
    teacher = get_user_model().objects.create_user(username="missing-vaultpub")
    asset = ClassroomAsset.objects.create(
        owner=teacher,
        source=ClassroomAsset.Source.SERVER_PATH,
        server_path=str(Path(tmp_path) / "missing.md"),
        original_name="missing.md",
        kind=ClassroomAsset.Kind.MARKDOWN,
        content_type="text/markdown; charset=utf-8",
        byte_size=1,
    )
    Path(asset.server_path).write_text("# Available", encoding="utf-8")
    asset.byte_size = Path(asset.server_path).stat().st_size
    asset.save(update_fields=["byte_size"])
    client = Client()
    client.force_login(teacher)
    response = client.get(reverse("liveclassroom:api-v1-document-root", args=[asset.public_id]))
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Document rendering is unavailable.",
        "code": "vaultpub_unavailable",
    }
    assert str(tmp_path) not in response.content.decode()
