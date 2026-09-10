import csv
import io
import json
from decimal import Decimal
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from liveclassroom.models import (
    AnswerRevision,
    AssessmentAttempt,
    AssessmentAttemptGrade,
    AssessmentAttemptItem,
    AssessmentItemGrade,
    AssessmentRun,
    Course,
    CourseMembership,
)
from liveclassroom.services.assessment_exports import (
    AssessmentExportError,
    student_result_projection,
    teacher_class_export,
    teacher_csv_export,
    teacher_json_export,
    teacher_run_export,
)


def _fixture():
    users = get_user_model()
    owner = users.objects.create_user(username="export-owner")
    student = users.objects.create_user(username="=student")
    other = users.objects.create_user(username="export-other")
    course = Course.objects.create(title="Export class", slug="export-class", created_by=owner)
    CourseMembership.objects.create(course=course, user=owner, role=CourseMembership.Role.TEACHER)
    CourseMembership.objects.create(course=course, user=student, role=CourseMembership.Role.STUDENT)
    run = AssessmentRun.objects.create(
        owner=owner,
        source_version=1,
        course=course,
        audience=AssessmentRun.Audience.CLASS,
        title="Unicode,\nexam",
        manifest={
            "settings": {
                "release_policy": {
                    "scores": "after_submit",
                    "answers": "never",
                    "explanations": "never",
                    "comments": "never",
                }
            }
        },
    )
    attempt = AssessmentAttempt.objects.create(
        run=run,
        user=student,
        attempt_number=1,
        status=AssessmentAttempt.Status.SUBMITTED,
        submitted_at=timezone.now(),
    )
    item = AssessmentAttemptItem.objects.create(
        attempt=attempt,
        key=uuid4(),
        position=1,
        points=Decimal("2"),
        manifest={
            "type_key": "liveclassroom.single_choice",
            "revision_id": 17,
            "payload": {
                "prompt": "Pick",
                "options": [{"id": "a", "text": "A"}],
                "answer": "a",
                "explanation": "private key",
            },
        },
    )
    answer = AnswerRevision.objects.create(
        item=item,
        version=1,
        answer={"choice": "a"},
        request_id=uuid4(),
        actor=student,
    )
    AssessmentItemGrade.objects.create(
        item=item,
        status=AssessmentItemGrade.Status.GRADED,
        normalized_score=Decimal("0.5"),
        possible_points=Decimal("2"),
        awarded_points=Decimal("1"),
        retained_answer=answer.answer,
        comment="teacher note",
    )
    AssessmentAttemptGrade.objects.create(
        attempt=attempt,
        status=AssessmentAttemptGrade.Status.GRADED,
        possible_points=Decimal("2"),
        awarded_points=Decimal("1"),
        graded_count=1,
    )
    return owner, student, other, course, run, attempt


@pytest.mark.django_db
def test_teacher_csv_selects_latest_and_neutralizes_user_text():
    owner, _student, _other, _course, run, _attempt = _fixture()
    projection = teacher_run_export(owner, run, details=False)
    rows = list(teacher_csv_export(projection))
    parsed = list(csv.DictReader(io.StringIO("".join(rows))))
    assert parsed[0]["student_identifier"] == "'=student"
    assert parsed[0]["earned_points"] == "1.00"
    assert parsed[0]["pending_count"] == "0"
    assert "items" not in projection["selected_attempts"][0]


@pytest.mark.django_db
def test_teacher_json_keeps_audit_but_omits_private_manifest_and_foreign_scope():
    owner, _student, other, course, run, _attempt = _fixture()
    projection = teacher_run_export(owner, run)
    payload = json.loads(next(iter(teacher_json_export(projection))))
    item = payload["attempts"][0]["items"][0]
    assert item["answer"] == {"choice": "a"}
    assert item["answer_revisions"][0]["actor_id"] is not None
    assert "payload" not in item
    with pytest.raises(AssessmentExportError):
        teacher_class_export(other, course)


@pytest.mark.django_db
def test_student_export_only_contains_released_dimensions_and_api_streams():
    owner, student, _other, _course, run, attempt = _fixture()
    projection = student_result_projection(student, attempt)
    item = projection["attempt"]["items"][0]
    assert "score" in item
    assert "answer" not in item
    assert "answer_key" not in item
    client = Client()
    client.force_login(student)
    response = client.get(
        reverse("liveclassroom:api-v1-attempt-result-export", args=[attempt.public_id]), {"format": "json"}
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    body = json.loads(b"".join(response.streaming_content))
    assert body["attempt"]["released"]["scores"] is True
    assert "private key" not in json.dumps(body)
    client.force_login(owner)
    denied = client.get(reverse("liveclassroom:api-v1-attempt-result-export", args=[attempt.public_id]))
    assert denied.status_code == 404
