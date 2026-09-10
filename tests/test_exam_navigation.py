"""Server-side forward-only navigation and countdown boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.services.assessment_navigation import (
    AttemptNavigationConflict,
    navigate_attempt,
    navigation_payload,
    save_and_advance_attempt,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition


def _attempt(owner, learner, *, navigation="forward_only", items=3):
    questions = [
        create_activity_definition(
            owner=owner,
            title=f"Question {index}",
            type_key="short_text",
            definition={"prompt": f"Question {index}"},
        )
        for index in range(1, items + 1)
    ]
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Exam",
            "settings": {"navigation": navigation, "max_attempts": 1},
            "items": [{"revision_id": question.current_revision_id} for question in questions],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    return start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())[0]


@pytest.mark.django_db
def test_forward_only_persists_cursor_locks_answer_and_rejects_stale_or_future_writes():
    users = get_user_model()
    owner = users.objects.create_user(username="exam-nav-owner")
    learner = users.objects.create_user(username="exam-nav-learner")
    attempt = _attempt(owner, learner)
    items = list(attempt.items.order_by("position"))

    with pytest.raises(AttemptNavigationConflict) as future:
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=items[1].key,
            answer={"text": "too soon"},
            expected_version=0,
            request_id=uuid4(),
        )
    assert future.value.code == "item_not_accessible"

    result = save_and_advance_attempt(
        actor=learner,
        attempt=attempt,
        current_item_key=items[0].key,
        expected_navigation_version=1,
        answer={"text": "first"},
        expected_answer_version=0,
        answer_request_id=uuid4(),
    )
    assert result["current_item_position"] == 2
    attempt.refresh_from_db()
    assert attempt.locked_item_keys == [str(items[0].key)]
    assert attempt.highest_accessible_item_position == 2

    with pytest.raises(AttemptNavigationConflict) as locked:
        save_attempt_answer(
            actor=learner,
            attempt=attempt,
            item_key=items[0].key,
            answer={"text": "overwrite"},
            expected_version=1,
            request_id=uuid4(),
        )
    assert locked.value.code == "item_locked"

    reviewed = navigate_attempt(
        actor=learner,
        attempt=attempt,
        item_key=items[0].key,
        expected_navigation_version=2,
    )
    assert reviewed["read_only"] is True
    assert reviewed["current_item_position"] == 1

    with pytest.raises(AttemptNavigationConflict) as stale:
        navigate_attempt(
            actor=learner,
            attempt=attempt,
            item_key=items[1].key,
            expected_navigation_version=2,
        )
    assert stale.value.code == "stale_navigation"


@pytest.mark.django_db
def test_free_navigation_keeps_all_reached_items_writable():
    users = get_user_model()
    owner = users.objects.create_user(username="exam-free-owner")
    learner = users.objects.create_user(username="exam-free-learner")
    attempt = _attempt(owner, learner, navigation="free", items=2)
    items = list(attempt.items.order_by("position"))
    first = save_and_advance_attempt(
        actor=learner,
        attempt=attempt,
        current_item_key=items[0].key,
        expected_navigation_version=1,
        answer={"text": "first"},
        expected_answer_version=0,
        answer_request_id=uuid4(),
    )
    assert first["current_item_position"] == 2
    save_attempt_answer(
        actor=learner,
        attempt=attempt,
        item_key=items[0].key,
        answer={"text": "revised"},
        expected_version=1,
        request_id=uuid4(),
    )
    assert attempt.items.get(pk=items[0].pk).answer_revisions.count() == 2


@pytest.mark.django_db
def test_navigation_payload_exposes_server_deadline_and_expiry_is_still_authoritative():
    users = get_user_model()
    owner = users.objects.create_user(username="exam-time-owner")
    learner = users.objects.create_user(username="exam-time-learner")
    attempt = _attempt(owner, learner, items=1)
    attempt.deadline_at = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    attempt.save(update_fields=["deadline_at"])
    payload = navigation_payload(attempt)
    assert payload["mode"] == "forward_only"
    assert payload["current_item_position"] == 1
    with pytest.raises(AttemptNavigationConflict, match="deadline"):
        navigate_attempt(
            actor=learner,
            attempt=attempt,
            item_key=attempt.items.get().key,
            expected_navigation_version=1,
            now=attempt.deadline_at,
        )
