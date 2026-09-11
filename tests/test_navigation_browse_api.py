"""Role-scoped course discovery for the course-first navigation surfaces."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import override_settings
from django.urls import reverse

from liveclassroom.models import Course, CourseMembership, TeachingCourse


@pytest.mark.django_db
def test_learning_browse_only_exposes_student_membership():
    users = get_user_model()
    teacher = users.objects.create_user(username="browse-teacher")
    learner = users.objects.create_user(username="browse-learner")
    other = users.objects.create_user(username="browse-other")
    program = TeachingCourse.objects.create(title="Biology", created_by=teacher)
    visible = Course.objects.create(
        title="Visible class", slug="browse-visible", created_by=teacher, teaching_course=program
    )
    hidden = Course.objects.create(
        title="Hidden class", slug="browse-hidden", created_by=teacher, teaching_course=program
    )
    CourseMembership.objects.create(course=visible, user=learner, role=CourseMembership.Role.STUDENT)
    CourseMembership.objects.create(course=hidden, user=other, role=CourseMembership.Role.STUDENT)
    client = Client()
    client.force_login(learner)

    index = client.get(reverse("liveclassroom:api-v1-browse-learning"))
    assert index.status_code == 200
    assert index.json()["courses"] == [
        {"id": program.id, "title": "Biology", "description": "", "url": f"/learn/courses/{program.id}/"}
    ]

    detail = client.get(reverse("liveclassroom:api-v1-browse-learning-course", args=[program.id]))
    assert detail.status_code == 200
    assert [item["class"]["title"] for item in detail.json()["classes"]] == ["Visible class"]
    assert client.get(reverse("liveclassroom:api-v1-browse-learning-class", args=[hidden.id])).status_code == 404


@pytest.mark.django_db
def test_home_and_navigation_browse_are_bounded_and_role_scoped():
    users = get_user_model()
    teacher = users.objects.create_user(username="navigation-home-teacher")
    learner = users.objects.create_user(username="navigation-home-learner")
    visible = Course.objects.create(title="Home visible", slug="navigation-home-visible", created_by=teacher)
    Course.objects.create(title="Home hidden", slug="navigation-home-hidden", created_by=teacher)
    CourseMembership.objects.create(course=visible, user=learner, role=CourseMembership.Role.STUDENT)

    with override_settings(LIVECLASSROOM={"TEACHER_AUTHORIZER": lambda actor: actor.pk == teacher.pk}):
        learner_client = Client()
        learner_client.force_login(learner)
        home = learner_client.get(reverse("liveclassroom:api-v1-browse-home"), {"mode": "learning"})
        assert home.status_code == 200
        assert home.json()["mode"] == "learning"
        classes = next(section for section in home.json()["sections"] if section["key"] == "classes")
        assert [item["title"] for item in classes["items"]] == ["Home visible"]
        navigation = learner_client.get(reverse("liveclassroom:api-v1-browse-navigation"))
        assert navigation.status_code == 200
        assert navigation.json()["modes"] == ["learning"]
        assert [item["title"] for item in navigation.json()["contexts"]] == ["Home visible"]

        teacher_client = Client()
        teacher_client.force_login(teacher)
        denied = teacher_client.get(reverse("liveclassroom:api-v1-browse-home"), {"mode": "other"})
        assert denied.status_code == 400
        teaching = teacher_client.get(reverse("liveclassroom:api-v1-browse-home"), {"mode": "teaching"})
        assert teaching.status_code == 200
        assert teaching.json()["mode"] == "teaching"
        assert {item["key"] for item in teaching.json()["quick_actions"]} == {
            "lesson",
            "deck",
            "assessment",
            "session",
        }


@pytest.mark.django_db
def test_navigation_reference_resolution_rechecks_access_and_hides_stale_items():
    users = get_user_model()
    teacher = users.objects.create_user(username="navigation-reference-teacher")
    learner = users.objects.create_user(username="navigation-reference-learner")
    visible = Course.objects.create(title="Resolved visible", slug="resolved-visible", created_by=teacher)
    hidden = Course.objects.create(title="Resolved hidden", slug="resolved-hidden", created_by=teacher)
    CourseMembership.objects.create(course=visible, user=learner, role=CourseMembership.Role.STUDENT)
    client = Client()
    client.force_login(learner)

    response = client.get(
        reverse("liveclassroom:api-v1-browse-navigation"),
        [("ref", f"class:{visible.id}:learning"), ("ref", f"class:{hidden.id}:learning"), ("ref", "deck:999999")],
    )
    assert response.status_code == 200
    assert response.json()["resolved"] == [
        {
            "ref": f"class:{visible.id}:learning",
            "label": "Resolved visible",
            "url": reverse("liveclassroom:learn-class-detail", args=[visible.id]),
            "kind": "class",
        }
    ]
    too_many = client.get(
        reverse("liveclassroom:api-v1-browse-navigation"),
        [("ref", "page:home")] * 23,
    )
    assert too_many.status_code == 400


@pytest.mark.django_db
def test_teaching_browse_keeps_other_teachers_courses_private():
    users = get_user_model()
    teacher = users.objects.create_user(username="browse-teaching-owner")
    other = users.objects.create_user(username="browse-teaching-other")
    own = TeachingCourse.objects.create(title="Own course", created_by=teacher)
    TeachingCourse.objects.create(title="Other course", created_by=other)
    Course.objects.create(title="Standalone", slug="browse-standalone", created_by=teacher)
    client = Client()
    client.force_login(teacher)

    response = client.get(reverse("liveclassroom:api-v1-browse-teaching"))
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["courses"]] == [own.id]
    assert [item["title"] for item in response.json()["independent_classes"]] == ["Standalone"]


@pytest.mark.django_db
def test_library_question_bank_and_class_results_are_addressable_destinations():
    users = get_user_model()
    teacher = users.objects.create_user(username="browse-results-owner")
    program = TeachingCourse.objects.create(title="Results course", created_by=teacher)
    cohort = Course.objects.create(
        title="Results class", slug="browse-results", created_by=teacher, teaching_course=program
    )
    client = Client()
    client.force_login(teacher)

    question_bank = client.get(reverse("liveclassroom:teacher-library-questions"))
    assert question_bank.status_code == 200
    assert b"data-question-bank-workspace" in question_bank.content

    results = client.get(reverse("liveclassroom:teacher-course-class-results", args=[program.id, cohort.id]))
    assert results.status_code == 200
    assert b"data-results-workspace" in results.content

    browse = client.get(reverse("liveclassroom:api-v1-browse-teaching-class", args=[cohort.id]))
    assert browse.status_code == 200
    assert browse.json()["results_url"] == reverse(
        "liveclassroom:teacher-course-class-results", args=[program.id, cohort.id]
    )


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.mounted_urls")
def test_learning_browse_reverses_navigation_urls_under_a_mount_prefix():
    users = get_user_model()
    teacher = users.objects.create_user(username="browse-mounted-teacher")
    learner = users.objects.create_user(username="browse-mounted-learner")
    program = TeachingCourse.objects.create(title="Mounted", created_by=teacher)
    cohort = Course.objects.create(
        title="Mounted cohort", slug="browse-mounted", created_by=teacher, teaching_course=program
    )
    CourseMembership.objects.create(course=cohort, user=learner, role=CourseMembership.Role.STUDENT)
    client = Client()
    client.force_login(learner)

    response = client.get(reverse("liveclassroom:api-v1-browse-learning"))
    assert response.status_code == 200
    assert response.json()["courses"][0]["url"] == f"/classroom/learn/courses/{program.id}/"
