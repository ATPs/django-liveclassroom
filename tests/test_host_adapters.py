from dataclasses import dataclass

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import Tags, run_checks
from django.test import RequestFactory, override_settings

from liveclassroom.integrations.host import (
    DefaultHostAdapter,
    HostActor,
    HostAdapterError,
    host_adapter,
    host_can_author,
    host_can_deliver,
    host_can_grade,
    host_can_view_named_responses,
    host_can_view_roster,
    host_list_roster,
)
from liveclassroom.services.classroom import ClassroomError, create_activity_definition


@dataclass
class FakeAdapter:
    author: bool = True
    deliver: bool = True
    roster: bool = True
    named: bool = True
    grade: bool = True
    seen_request: object | None = None

    def resolve_actor(self, *, request):
        self.seen_request = request
        if not getattr(request.user, "is_authenticated", False):
            return None
        return HostActor(id=f"host-{request.user.pk}", display_name="Delegated teacher")

    def can_author(self, *, actor, resource):
        return self.author

    def can_deliver(self, *, actor, resource):
        return self.deliver

    def can_view_roster(self, *, actor, course_id):
        return self.roster

    def can_view_named_responses(self, *, actor, session_id):
        return self.named

    def can_grade(self, *, actor, attempt_id):
        return self.grade

    def course_summary(self, *, actor, course_id):
        return {"course_id": course_id, "fingerprint": actor.fingerprint}

    def list_roster(self, *, actor, course_id):
        return [{"id": "student-1", "display_name": "Learner"}]


def test_default_adapter_is_standalone_safe_and_host_only_capabilities_fail_closed():
    user = get_user_model()(pk=7, username="teacher")
    assert host_adapter().__class__ is DefaultHostAdapter
    assert host_can_author(actor=user, resource=None)
    assert host_can_deliver(actor=user, resource=None)
    assert not host_can_view_roster(actor=user, course_id=1)
    assert not host_can_view_named_responses(actor=user, session_id=1)
    assert not host_can_grade(actor=user, attempt_id=1)
    assert host_can_view_named_responses(actor=user, session_id=1, package_allowed=True)
    assert host_list_roster(actor=user, course_id=1) == []


@pytest.mark.django_db
def test_configured_adapter_is_request_aware_and_rechecked_for_each_capability():
    user = get_user_model().objects.create_user(username="delegated-teacher")
    request = RequestFactory().get("/classroom/")
    request.user = user
    adapter = FakeAdapter()
    with override_settings(LIVECLASSROOM={"HOST_ADAPTER": adapter}):
        assert host_can_author(actor=user, resource="question", request=request)
        assert adapter.seen_request is request
        assert host_can_view_roster(actor=user, course_id=12, request=request)
        assert host_can_view_named_responses(actor=user, session_id=9, request=request)
        assert host_can_grade(actor=user, attempt_id=3, request=request)
        roster = host_list_roster(actor=user, course_id=12, request=request)
        assert roster[0]["id"] == "student-1"
        assert len(roster[0]["fingerprint"]) == 64
        adapter.author = False
        assert not host_can_author(actor=user, resource="question", request=request)
        adapter.deliver = False
        assert not host_can_deliver(actor=user, resource="run", request=request)
        adapter.named = False
        assert not host_can_view_named_responses(actor=user, session_id=9, request=request, package_allowed=True)
        adapter.grade = False
        assert not host_can_grade(actor=user, attempt_id=3, request=request, package_allowed=True)


def test_malformed_adapter_is_reported_and_does_not_grant_access():
    with override_settings(LIVECLASSROOM={"HOST_ADAPTER": object()}):
        with pytest.raises(HostAdapterError):
            host_adapter()
        messages = run_checks(tags=[Tags.compatibility])
        assert any(message.id == "liveclassroom.E008" for message in messages)


@pytest.mark.django_db
def test_authoring_is_denied_before_persisting_when_host_policy_denies():
    owner = get_user_model().objects.create_user(username="host-denied-author")
    adapter = FakeAdapter(author=False)
    with override_settings(LIVECLASSROOM={"HOST_ADAPTER": adapter}):
        with pytest.raises(ClassroomError, match="host does not allow"):
            create_activity_definition(
                owner=owner,
                title="Denied",
                type_key="single_choice",
                definition={"options": [{"id": "a", "text": "A"}]},
            )
