import json

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, override_settings
from django.urls import reverse

from liveclassroom.models import Course, CourseMembership, LiveSession, TeachingCourse
from liveclassroom.services.organization import (
    OrganizationConflict,
    assign_class,
    create_teaching_course,
    delete_teaching_course,
    list_teaching_courses,
    unassign_class,
    update_teaching_course,
)


def api(client, method, name, payload=None, args=(), key=None):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    return getattr(client, method)(
        reverse(name, args=args),
        data=json.dumps(payload) if payload is not None else None,
        content_type="application/json",
        **headers,
    )


def cohort(owner, title, slug):
    return Course.objects.create(title=title, slug=slug, created_by=owner)


@pytest.mark.django_db
def test_services_keep_cohorts_and_teaching_history_when_grouping_changes():
    users = get_user_model()
    teacher = users.objects.create_user(username="organization-owner")
    first = cohort(teacher, "Class A", "class-a")
    second = cohort(teacher, "Class B", "class-b")
    member = users.objects.create_user(username="organization-member")
    CourseMembership.objects.create(course=second, user=member, role=CourseMembership.Role.STUDENT)
    session = LiveSession.objects.create(teacher=teacher, course=second, title="Retained session")
    one = create_teaching_course(actor=teacher, title="  Biostatistics  ")
    two = create_teaching_course(actor=teacher, title="Statistics II", description="2026")

    assert one.title == "Biostatistics"
    assert one.description == ""
    updated = update_teaching_course(actor=teacher, teaching_course=one, changes={"description": "updated"})
    assert updated.description == "updated"
    assert [item.id for item in list_teaching_courses(actor=teacher)] == [one.id, two.id]
    assert assign_class(actor=teacher, teaching_course=one, cohort=first).teaching_course_id == one.id
    assert assign_class(actor=teacher, teaching_course=one, cohort=second).teaching_course_id == one.id
    assert assign_class(actor=teacher, teaching_course=two, cohort=first).teaching_course_id == two.id
    assert unassign_class(actor=teacher, teaching_course=two, cohort=first).teaching_course_id is None
    assert unassign_class(actor=teacher, teaching_course=two, cohort=first).teaching_course_id is None

    delete_teaching_course(actor=teacher, teaching_course=one)
    second.refresh_from_db()
    assert second.teaching_course_id is None
    assert second.memberships.get().user_id == member.id
    assert LiveSession.objects.get(pk=session.pk).course_id == second.id


@pytest.mark.django_db
def test_services_enforce_owner_host_policy_and_association_conflicts():
    users = get_user_model()
    owner = users.objects.create_user(username="organization-owner")
    other = users.objects.create_user(username="organization-other")
    assistant = users.objects.create_user(username="organization-assistant")
    superuser = users.objects.create_superuser(username="organization-admin", password="unused", email="a@example.test")
    group = create_teaching_course(actor=owner, title="Owner group")
    other_group = create_teaching_course(actor=owner, title="Other group")
    owned = cohort(owner, "Owned", "owned")
    foreign = cohort(other, "Foreign", "foreign")
    CourseMembership.objects.create(course=owned, user=assistant, role=CourseMembership.Role.ASSISTANT)

    with pytest.raises(PermissionDenied):
        assign_class(actor=assistant, teaching_course=group, cohort=owned)
    with pytest.raises(ValidationError):
        assign_class(actor=superuser, teaching_course=group, cohort=foreign)
    assign_class(actor=owner, teaching_course=group, cohort=owned)
    with pytest.raises(OrganizationConflict):
        unassign_class(actor=owner, teaching_course=other_group, cohort=owned)
    with override_settings(LIVECLASSROOM={"TEACHER_AUTHORIZER": lambda actor: False}):
        with pytest.raises(PermissionDenied):
            create_teaching_course(actor=superuser, title="Denied by host")


@pytest.mark.django_db
def test_api_create_read_update_associate_and_idempotency(client):
    user = get_user_model().objects.create_user(username="api-owner")
    first = cohort(user, "Class A", "api-class-a")
    second = cohort(user, "Class B", "api-class-b")
    client.force_login(user)
    created = api(
        client,
        "post",
        "liveclassroom:api-v1-teaching-courses",
        {"title": "  Biology  ", "description": "2026"},
        key="teaching-course-create",
    )
    assert created.status_code == 201
    assert created.json() == {
        "id": created.json()["id"],
        "title": "Biology",
        "description": "2026",
        "owner_id": user.id,
    }
    course_id = created.json()["id"]
    replay = api(
        client,
        "post",
        "liveclassroom:api-v1-teaching-courses",
        {"title": "  Biology  ", "description": "2026"},
        key="teaching-course-create",
    )
    assert replay.status_code == 201 and replay.json() == created.json()
    assert TeachingCourse.objects.filter(created_by=user).count() == 1
    assert api(
        client,
        "post",
        "liveclassroom:api-v1-teaching-courses",
        {"title": "Changed"},
        key="teaching-course-create",
    ).status_code == 409
    assert api(
        client,
        "post",
        "liveclassroom:api-v1-teaching-course-classes",
        {"class_id": first.id},
        [course_id],
    ).json() == {"class_id": first.id, "teaching_course_id": course_id}
    assert api(
        client,
        "post",
        "liveclassroom:api-v1-teaching-course-classes",
        {"class_id": second.id},
        [course_id],
    ).status_code == 200
    detail = client.get(reverse("liveclassroom:api-v1-teaching-course-detail", args=[course_id]))
    assert detail.status_code == 200
    assert detail.json()["classes"] == [{"id": first.id, "title": "Class A"}, {"id": second.id, "title": "Class B"}]
    changed = api(client, "patch", "liveclassroom:api-v1-teaching-course-detail", {}, [course_id])
    assert changed.status_code == 200 and changed.json()["title"] == "Biology"
    assert api(
        client, "delete", "liveclassroom:api-v1-teaching-course-class", args=[course_id, first.id]
    ).json() == {"class_id": first.id, "teaching_course_id": None}
    assert api(
        client, "delete", "liveclassroom:api-v1-teaching-course-detail", args=[course_id]
    ).json() == {"deleted": True}
    second.refresh_from_db()
    assert second.teaching_course_id is None


@pytest.mark.django_db
def test_api_rejects_invalid_payloads_and_preserves_existing_class_api(client):
    user = get_user_model().objects.create_user(username="api-validation")
    client.force_login(user)
    url = reverse("liveclassroom:api-v1-teaching-courses")
    for payload in ({}, {"title": " "}, {"title": "x", "description": None}, {"title": "x", "owner_id": 1}):
        assert client.post(url, data=json.dumps(payload), content_type="application/json").status_code == 400
    assert client.post(url, data="[]", content_type="application/json").status_code == 400
    assert client.post(url, data="{", content_type="application/json").status_code == 400
    created = client.post(url, data=json.dumps({"title": "Valid"}), content_type="application/json")
    assert created.json()["description"] == ""
    class_url = reverse("liveclassroom:api-v1-teaching-course-classes", args=[created.json()["id"]])
    for payload in ({}, {"class_id": True}, {"class_id": "7"}, {"class_id": 0}, {"class_id": 7, "extra": True}):
        assert client.post(class_url, data=json.dumps(payload), content_type="application/json").status_code == 400
    invalid = client.post(
        url,
        data=json.dumps({"title": " "}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid-create",
    )
    assert invalid.status_code == 400
    assert client.post(
        url,
        data=json.dumps({"title": "Recovered"}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid-create",
    ).status_code == 201
    assert client.get(reverse("liveclassroom:api-v1-courses")).json() == {"courses": []}


@pytest.mark.django_db
def test_api_permissions_mounted_urls_and_csrf():
    users = get_user_model()
    owner = users.objects.create_user(username="mounted-owner")
    other = users.objects.create_user(username="mounted-other")
    group = create_teaching_course(actor=owner, title="Private")
    anonymous = Client()
    detail = reverse("liveclassroom:api-v1-teaching-course-detail", args=[group.id])
    assert anonymous.get(detail).status_code == 401
    other_client = Client()
    other_client.force_login(other)
    assert other_client.get(detail).status_code == 403
    with override_settings(ROOT_URLCONF="tests.mounted_urls"):
        assert reverse("liveclassroom:api-v1-teaching-courses") == "/classroom/api/v1/teaching-courses/"

    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(owner)
    with override_settings(
        MIDDLEWARE=[
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
        ]
    ):
        response = csrf_client.post(
            reverse("liveclassroom:api-v1-teaching-courses"),
            data=json.dumps({"title": "CSRF"}),
            content_type="application/json",
        )
    assert response.status_code == 403
