import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from liveclassroom.models import Course, Flow, LiveSession


@pytest.mark.django_db
def test_live_session_requires_flow_from_its_course():
    user = get_user_model().objects.create_user(username="teacher")
    course = Course.objects.create(title="Course A", slug="course-a", created_by=user)
    other_course = Course.objects.create(title="Course B", slug="course-b", created_by=user)
    other_flow = Flow.objects.create(course=other_course, title="Other flow", slug="other-flow")

    session = LiveSession(course=course, flow=other_flow, teacher=user)

    with pytest.raises(ValidationError, match="selected flow"):
        session.full_clean()
