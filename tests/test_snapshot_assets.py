"""Retained classroom files survive removal and revocation of their source."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError

from liveclassroom.models import FlowShare
from liveclassroom.services.assets import create_uploaded_asset
from liveclassroom.services.classroom import create_activity_definition, start_session
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.plans import create_session, launch_plan_step, save_lesson


@pytest.mark.django_db
def test_snapshot_keeps_upload_after_shared_source_is_revoked_and_deleted():
    users = get_user_model()
    owner = users.objects.create_user(username="asset-snapshot-owner")
    recipient = users.objects.create_user(username="asset-snapshot-recipient")
    asset = create_uploaded_asset(
        owner=owner, uploaded_file=SimpleUploadedFile("notes.md", b"# Retained teaching notes")
    )
    definition = create_activity_definition(
        owner=owner,
        title="Notes",
        type_key="liveclassroom.file",
        definition={"asset_id": str(asset.public_id), "file_kind": asset.kind},
        asset=asset,
    )
    flow = create_flow(creator=owner, title="Shared notes")
    add_flow_step(flow=flow, actor=owner, activity_definition=definition)
    FlowShare.objects.create(flow=flow, user=recipient)
    session = create_session(owner=recipient, title="Retained classroom", flow=flow)
    flow.delete()
    definition.delete()
    with pytest.raises(ProtectedError):
        asset.delete()
    session.refresh_from_db()
    assert session.flow_id is None
    assert session.source_snapshot.assets.get().pk == asset.pk
    start_session(session=session, actor=recipient)
    activity = launch_plan_step(session=session, step=session.plan_steps.get(), actor=recipient)
    assert activity.current_revision.asset_id == asset.pk
    saved = save_lesson(session=session, actor=recipient, title="My retained notes")
    assert saved.steps.get().activity_definition.asset_id == asset.pk
