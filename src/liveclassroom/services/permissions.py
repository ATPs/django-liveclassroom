"""Centralized permission helpers shared by the classroom and flow services.

Keeping these in one place avoids the classroom and flow modules drifting apart
on who may author a course, edit a flow, or reference a reusable activity.
"""

from __future__ import annotations

from liveclassroom.models import Course, CourseMembership, Flow


def can_author_course(actor, course: Course | None) -> bool:
    """Whether an actor may author reusable content for a course.

    ``course=None`` means authoring outside any course, which any authenticated
    teacher may do.
    """
    if not getattr(actor, "is_authenticated", False):
        return False
    if course is None:
        return True
    if getattr(actor, "is_superuser", False):
        return True
    if course.created_by_id == actor.pk:
        return True
    return CourseMembership.objects.filter(
        course_id=course.id,
        user=actor,
        role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
    ).exists()


def can_edit_flow(actor, flow: Flow) -> bool:
    """Whether an actor may edit a flow: creator, course owner, or course staff."""
    if not getattr(actor, "is_authenticated", False):
        return False
    if getattr(actor, "is_superuser", False):
        return True
    if flow.created_by_id and flow.created_by_id == actor.pk:
        return True
    if flow.course_id:
        if flow.course and flow.course.created_by_id == actor.pk:
            return True
        return CourseMembership.objects.filter(
            course_id=flow.course_id,
            user=actor,
            role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
        ).exists()
    return False


def can_use_activity_definition(actor, activity) -> bool:
    """Whether an actor may reference a reusable activity definition.

    An actor may use a definition they own, any course-scoped definition for a
    course they may author, or anything when they are a superuser. Private
    definitions remain owner-only.
    """
    if not getattr(actor, "is_authenticated", False):
        return False
    if getattr(actor, "is_superuser", False) or activity.owner_id == actor.pk:
        return True
    if not activity.course_id:
        return False
    if CourseMembership.objects.filter(
        course_id=activity.course_id,
        user=actor,
        role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
    ).exists():
        return True
    return Course.objects.filter(pk=activity.course_id, created_by=actor).exists()
