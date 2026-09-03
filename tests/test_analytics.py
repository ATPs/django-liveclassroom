import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from liveclassroom.models import SessionMessage, SessionStaff
from liveclassroom.services.classroom import (
    create_activity_definition,
    create_instant_session,
    join_guest,
    launch_item,
    mark_participant_connected,
    revise_activity,
    start_session,
    submit_answer,
)


@pytest.mark.django_db
def test_staff_session_analytics_reports_attendance_responses_and_revision_timeline():
    teacher = get_user_model().objects.create_user(username="analytics-teacher", password="password")
    observer = get_user_model().objects.create_user(username="analytics-observer", password="password")
    session = create_instant_session(owner=teacher, title="Analytics class")
    SessionStaff.objects.create(session=session, user=observer, role=SessionStaff.Role.OBSERVER)
    definition = create_activity_definition(
        owner=teacher,
        title="Pick one",
        type_key="liveclassroom.single_choice",
        definition={"options": [{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}]},
    )
    start_session(session=session, actor=teacher)
    activity = launch_item(session=session, item=definition, actor=teacher)
    first = join_guest(session=session, display_name="Ada")
    second = join_guest(session=session, display_name="Grace")
    mark_participant_connected(participant=first)
    submit_answer(activity=activity, participant=first, answer={"choice": "A"})
    session.chat_enabled = True
    session.save(update_fields=["chat_enabled"])
    SessionMessage.objects.create(session=session, participant=first, display_name="Ada", body="Can you repeat that?")

    teacher_client = Client()
    teacher_client.force_login(teacher)
    analytics_url = reverse("liveclassroom:api-v1-analytics", args=[session.id])
    initial = teacher_client.get(analytics_url)
    assert initial.status_code == 200
    payload = initial.json()
    assert payload["attendance"] == {
        "total": 2,
        "eligible": 2,
        "admitted": 2,
        "pending": 0,
        "rejected": 0,
        "removed": 0,
        "ever_connected": 1,
        "currently_connected": 1,
    }
    activity_data = payload["activities"][0]
    assert activity_data["submitted_count"] == 1
    assert activity_data["unanswered_count"] == 1
    assert activity_data["response_rate"] == 50.0
    assert activity_data["aggregate"]["choices"] == {"A": 1}
    assert activity_data["responses"][0]["display_name"] == "Ada"
    assert payload["participants"][1]["timeline"] == []
    assert payload["chat"]["enabled"] is True
    assert payload["chat"]["messages"][0]["body"] == "Can you repeat that?"

    revise_activity(
        activity=activity,
        definition_snapshot={
            "type_key": "liveclassroom.single_choice",
            "kind": "single_choice",
            "title": "Pick one, revised",
            "content": {"options": [{"id": "B", "text": "Second"}]},
        },
        actor=teacher,
    )
    revised = teacher_client.get(analytics_url).json()
    revised_activity = revised["activities"][0]
    assert revised_activity["submitted_count"] == 0
    assert revised_activity["stale_submission_count"] == 1
    assert revised["participants"][0]["current_response_count"] == 0
    assert revised["participants"][0]["stale_response_count"] == 1
    assert revised["participants"][0]["timeline"][0]["revision_count"] == 1

    student_client = Client()
    student_client.session[f"liveclassroom.participant.{session.id}"] = second.id
    student_client.session.save()
    assert student_client.get(analytics_url).status_code == 403

    observer_client = Client()
    observer_client.force_login(observer)
    assert observer_client.get(analytics_url).status_code == 200
