import pytest
from django.contrib.auth import get_user_model

from liveclassroom.models import Course, Flow, LiveSession


@pytest.mark.django_db
def test_live_session_allows_reusable_lesson_from_another_course():
    user = get_user_model().objects.create_user(username="teacher")
    course = Course.objects.create(title="Course A", slug="course-a", created_by=user)
    other_course = Course.objects.create(title="Course B", slug="course-b", created_by=user)
    other_flow = Flow.objects.create(course=other_course, title="Other flow", slug="other-flow")

    session = LiveSession(course=course, flow=other_flow, teacher=user, title="Cross-class lesson")

    session.full_clean()
    session.save()
    assert session.source_snapshot_id is not None
