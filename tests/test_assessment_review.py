"""Own assessment history and retained review contracts."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import AssessmentRun
from liveclassroom.services.assessment_review import (
    AssessmentReviewError,
    list_own_attempt_history,
    review_own_attempt,
)
from liveclassroom.services.assessment_runs import publish_assessment
from liveclassroom.services.assessments import create_assessment
from liveclassroom.services.attempt_submission import submit_attempt
from liveclassroom.services.attempts import save_attempt_answer, start_or_resume_attempt
from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.result_release import release_result_dimension


def _fixture():
    users = get_user_model()
    owner = users.objects.create_user(username=f"review-owner-{uuid4().hex[:8]}")
    learner = users.objects.create_user(username=f"review-learner-{uuid4().hex[:8]}")
    other = users.objects.create_user(username=f"review-other-{uuid4().hex[:8]}")
    question = create_activity_definition(
        owner=owner,
        title="Original question",
        type_key="single_choice",
        definition={
            "prompt": "Original prompt", "options": [{"id": "a", "text": "One"}],
            "answer": "a", "explanation": "Original explanation",
        },
    )
    assessment = create_assessment(
        actor=owner,
        data={
            "title": "Review run",
            "settings": {"audience": AssessmentRun.Audience.AUTHENTICATED_LINK, "max_attempts": None},
            "items": [{"revision_id": question.current_revision_id, "points": "2"}],
        },
    )
    run = publish_assessment(actor=owner, assessment=assessment, expected_version=assessment.version)
    attempt, _ = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4())
    item = attempt.items.get()
    save_attempt_answer(
        actor=learner, attempt=attempt, item_key=item.key, answer={"choice": "a"},
        expected_version=0, request_id=uuid4(),
    )
    submit_attempt(actor=learner, attempt=attempt, request_id=uuid4(), expected_versions={str(item.key): 1})
    return owner, learner, other, question, run, attempt, item


@pytest.mark.django_db
def test_history_is_read_only_newest_first_and_marks_resume():
    owner, learner, _other, _question, run, submitted, _item = _fixture()
    active, created = start_or_resume_attempt(actor=learner, run=run, request_id=uuid4(), new_attempt=True)
    assert created
    before = run.attempts.count()
    payload = list_own_attempt_history(actor=learner, limit=1, offset=0)
    assert payload["total"] == 2 and len(payload["items"]) == 1
    assert payload["items"][0]["id"] == str(active.public_id)
    assert payload["items"][0]["can_resume"] is True
    assert run.attempts.count() == before
    next_page = list_own_attempt_history(actor=learner, limit=1, offset=1)
    assert next_page["items"][0]["id"] == str(submitted.public_id)


@pytest.mark.django_db
def test_review_uses_retained_content_and_own_answer_but_hides_result_dimensions():
    owner, learner, _other, question, _run, attempt, _item = _fixture()
    question.title = "Changed after publish"
    question.definition = {"prompt": "Changed prompt", "options": [{"id": "x", "text": "Changed"}], "answer": "x"}
    question.save(update_fields=["title", "definition"])
    payload = review_own_attempt(actor=learner, public_id=attempt.public_id)
    row = payload["items"][0]
    assert row["content"]["prompt"] == "Original prompt"
    assert row["saved_answer"] == {"choice": "a"}
    assert row["released"] == {"scores": False, "answers": False, "explanations": False, "comments": False}
    assert "answer_key" not in row["result"] and "explanation" not in row["result"]
    assert "score" not in row["result"]


@pytest.mark.django_db
def test_review_rechecks_release_and_never_allows_foreign_attempt():
    owner, learner, other, _question, run, attempt, _item = _fixture()
    release_result_dimension(run=run, attempt=attempt, dimension="answers", actor=owner)
    allowed = review_own_attempt(actor=learner, public_id=attempt.public_id)
    assert allowed["items"][0]["result"]["answer_key"] == "a"
    with pytest.raises(AssessmentReviewError, match="not found"):
        review_own_attempt(actor=other, public_id=attempt.public_id)
