"""Service-level tests for the v1 portable content graph."""

import base64
import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from liveclassroom.models import ActivityDefinition, ClassroomAsset
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.decks import create_deck
from liveclassroom.services.flows import add_flow_step, create_flow
from liveclassroom.services.portable_content import (
    PortableContentError,
    PortablePermissionError,
    export_portable,
    import_portable,
    validate_portable,
)
from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank


def _question(owner, title="Cell"):
    return create_activity_definition(
        owner=owner,
        title=title,
        type_key="liveclassroom.single_choice",
        definition={
            "prompt": "Which organelle contains DNA?",
            "options": [{"id": "A", "text": "Nucleus"}, {"id": "B", "text": "Ribosome"}],
            "answer": "A",
        },
        metadata={"topic": "biology", "tags": ["cell"]},
    )


def _envelope(**overrides):
    result = {
        "format": "liveclassroom.portable",
        "version": 1,
        "activities": [],
        "decks": [],
        "assessments": [],
        "banks": [],
        "flows": [],
        "assets": [],
    }
    result.update(overrides)
    return result


@pytest.mark.django_db
def test_activity_export_is_deterministic_and_excludes_database_ids():
    owner = get_user_model().objects.create_user(username=f"portable-owner-{uuid4().hex[:8]}")
    activity = _question(owner)
    first = export_portable(actor=owner, kind="activity", object_id=activity.pk)
    second = export_portable(actor=owner, kind="question", object_id=activity.pk)
    assert first == second
    assert first["activities"][0]["key"] == "activity-1"
    assert first["activities"][0]["definition"]["answer"] == "A"
    assert "id" not in first["activities"][0]
    assert "owner_id" not in repr(first)
    imported = import_portable(actor=owner, payload=first)
    copied = imported.activities[0]
    assert copied.pk != activity.pk
    assert copied.owner_id == owner.pk
    assert copied.definition == activity.definition


@pytest.mark.django_db
def test_bank_export_deduplicates_a_question_selected_by_two_memberships():
    owner = get_user_model().objects.create_user(username=f"portable-bank-{uuid4().hex[:8]}")
    activity = _question(owner)
    first = create_question_bank(actor=owner, data={"title": "One"})
    second = create_question_bank(actor=owner, data={"title": "Two"})
    add_question_to_bank(actor=owner, bank=first, definition=activity)
    add_question_to_bank(actor=owner, bank=second, definition=activity)
    payload = export_portable(actor=owner, kind="bank", object_id=first.pk)
    assert len(payload["activities"]) == 1
    assert payload["banks"][0]["question_keys"] == ["activity-1"]
    result = import_portable(actor=owner, payload=payload)
    assert len(result.banks) == 1
    assert result.banks[0].items.count() == 1
    assert result.banks[0].items.get().definition_id == result.activities[0].pk


@pytest.mark.django_db
def test_deck_and_flow_exports_preserve_order_and_import_as_new_objects():
    owner = get_user_model().objects.create_user(username=f"portable-deck-{uuid4().hex[:8]}")
    activity = _question(owner)
    deck = create_deck(
        actor=owner,
        data={
            "title": "Intro",
            "theme": "dark",
            "slides": [
                {"markdown": "# First\n\n```python\n---\n```", "notes": "private 1"},
                {"markdown": "# Second", "notes": "private 2"},
            ],
        },
    )
    flow = create_flow(title="Lesson", creator=owner)
    add_flow_step(flow=flow, actor=owner, activity_definition=activity, position=1)
    deck_payload = export_portable(actor=owner, kind="deck", object_id=deck.pk)
    flow_payload = export_portable(actor=owner, kind="flow", object_id=flow.pk)
    assert [slide["position"] for slide in deck_payload["decks"][0]["slides"]] == [1, 2]
    assert deck_payload["decks"][0]["slides"][0]["notes"] == "private 1"
    assert flow_payload["flows"][0]["steps"] == ["activity-1"]
    imported_deck = import_portable(actor=owner, payload=deck_payload).decks[0]
    imported_flow = import_portable(actor=owner, payload=flow_payload).flows[0]
    assert imported_deck.pk != deck.pk
    assert list(imported_deck.slides.values_list("markdown", flat=True)) == [
        "# First\n\n```python\n---\n```",
        "# Second",
    ]
    assert imported_flow.steps.count() == 1


@pytest.mark.django_db
def test_assessment_export_round_trip_preserves_points_and_private_key():
    owner = get_user_model().objects.create_user(username=f"portable-assessment-{uuid4().hex[:8]}")
    activity = _question(owner)
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Quiz",
            "instructions": "Read carefully",
            "items": [{"revision_id": activity.current_revision_id, "points": "2.50"}],
        },
    )
    payload = export_portable(actor=owner, kind="assessment", object_id=assessment.pk)
    assert payload["assessments"][0]["items"][0]["points"] == "2.5"
    assert payload["activities"][0]["definition"]["answer"] == "A"
    copied = import_portable(actor=owner, payload=payload).assessments[0]
    assert copied.items.get().points == assessment.items.get().points
    assert copied.items.get().question_revision.payload["answer"] == "A"


@pytest.mark.django_db
def test_assessment_pool_graph_round_trip_is_atomic_and_retains_section_rules():
    owner = get_user_model().objects.create_user(username=f"portable-pool-{uuid4().hex[:8]}")
    fixed = _question(owner, "Fixed")
    candidate = _question(owner, "Candidate")
    bank = create_question_bank(actor=owner, data={"title": "Pool"})
    add_question_to_bank(actor=owner, bank=bank, definition=candidate)
    item_key = str(uuid4())
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Pooled quiz",
            "items": [{"key": item_key, "revision_id": fixed.current_revision_id, "points": "3"}],
            "sections": [
                {
                    "title": "Section",
                    "entries": [
                        {"kind": "fixed", "item_key": item_key},
                        {"kind": "pool", "bank_id": bank.pk, "sample_size": 1, "points": "2"},
                    ],
                }
            ],
        },
    )
    # The fixed item key is preserved in the portable graph independently of
    # the database primary key.
    payload = export_portable(actor=owner, kind="assessment", object_id=assessment.pk)
    assert payload["assessments"][0]["sections"][0]["entries"][1]["bank_key"] == "bank-1"
    result = import_portable(actor=owner, payload=payload)
    copied = result.assessments[0]
    assert copied.sections.count() == 1
    assert copied.sections.get().entries.filter(kind="pool", sample_size=1).count() == 1
    assert result.banks[0].items.count() == 1


def test_validation_rejects_unknown_fields_duplicate_keys_sensitive_fields_and_dangling_references():
    activity = {
        "key": "activity-1",
        "type_key": "liveclassroom.single_choice",
        "schema_version": 1,
        "title": "Question",
        "definition": {"prompt": "Q", "options": [{"id": "A", "text": "A"}], "answer": "A"},
        "metadata": {},
    }
    with pytest.raises(PortableContentError, match="unsupported"):
        validate_portable(_envelope(activities=[{**activity, "unexpected": True}]))
    with pytest.raises(PortableContentError, match="Duplicate"):
        validate_portable(_envelope(activities=[activity, deepcopy(activity)]))
    with pytest.raises(PortableContentError, match="not portable"):
        validate_portable(
            _envelope(activities=[{**activity, "definition": {**activity["definition"], "attempts": []}}])
        )
    with pytest.raises(PortableContentError, match="missing activity"):
        validate_portable(
            _envelope(banks=[{"key": "bank-1", "title": "B", "description": "", "question_keys": ["missing"]}])
        )


def test_asset_limits_and_path_safety_are_checked_before_import():
    raw = b"safe bytes"
    asset = {
        "key": "asset-1",
        "filename": "figure.png",
        "content_type": "image/png",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": "base64",
        "data": base64.b64encode(raw).decode(),
    }
    valid = validate_portable(_envelope(assets=[asset]))
    assert valid.payload["assets"][0]["filename"] == "figure.png"
    with pytest.raises(PortableContentError, match="plain filename"):
        validate_portable(_envelope(assets=[{**asset, "filename": "../figure.png"}]))
    with pytest.raises(PortableContentError, match="sha256"):
        validate_portable(_envelope(assets=[{**asset, "sha256": "0" * 64}]))


@pytest.mark.django_db
def test_export_requires_exact_owner_and_failed_import_has_no_partial_objects():
    users = get_user_model()
    owner = users.objects.create_user(username=f"portable-owner2-{uuid4().hex[:8]}")
    other = users.objects.create_user(username=f"portable-other-{uuid4().hex[:8]}")
    activity = _question(owner)
    with pytest.raises(PortablePermissionError):
        export_portable(actor=other, kind="activity", object_id=activity.pk)
    payload = _envelope(
        activities=[
            {
                "key": "activity-1",
                "type_key": "liveclassroom.single_choice",
                "schema_version": 1,
                "title": "Valid",
                "definition": {"prompt": "Q", "options": [{"id": "A", "text": "A"}], "answer": "A"},
                "metadata": {},
            },
            {
                "key": "activity-2",
                "type_key": "liveclassroom.unknown",
                "schema_version": 1,
                "title": "Invalid",
                "definition": {},
                "metadata": {},
            },
        ]
    )
    before = ActivityDefinition.objects.count()
    with pytest.raises(PortableContentError):
        import_portable(actor=owner, payload=payload)
    assert ActivityDefinition.objects.count() == before


@pytest.mark.django_db
def test_uploaded_asset_is_copied_through_asset_service_and_is_independent(tmp_path, settings):
    owner = get_user_model().objects.create_user(username=f"portable-asset-{uuid4().hex[:8]}")
    asset = ClassroomAsset.objects.create(
        owner=owner,
        source=ClassroomAsset.Source.UPLOAD,
        original_name="notes.md",
        kind=ClassroomAsset.Kind.MARKDOWN,
        content_type="text/markdown; charset=utf-8",
        byte_size=9,
        sha256=hashlib.sha256(b"# Notes\n").hexdigest(),
    )
    asset.content_file.save("notes.md", SimpleUploadedFile("notes.md", b"# Notes\n"), save=True)
    activity = create_activity_definition(
        owner=owner,
        title="Handout",
        type_key="liveclassroom.file",
        definition={"asset_id": str(asset.public_id), "file_kind": "markdown"},
        asset=asset,
    )
    payload = export_portable(actor=owner, kind="activity", object_id=activity.pk)
    assert payload["assets"][0]["data"]
    result = import_portable(actor=owner, payload=payload)
    assert result.assets[0].pk != asset.pk
    assert result.activities[0].asset_id == result.assets[0].pk
