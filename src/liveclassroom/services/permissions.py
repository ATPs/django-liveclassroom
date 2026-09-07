"""Centralized permission helpers shared by the classroom and flow services.

Keeping these in one place avoids the classroom and flow modules drifting apart
on who may author a course, edit a flow, or reference a reusable activity.
"""

from __future__ import annotations

from liveclassroom.conf import teacher_authorizer
from liveclassroom.models import Course, CourseMembership, Flow


def can_teach(actor) -> bool:
    """Apply a host's optional teacher policy without weakening package defaults."""
    if not getattr(actor, "is_authenticated", False):
        return False
    authorizer = teacher_authorizer()
    if authorizer is None:
        return True
    try:
        decision = authorizer(actor)
    except Exception:
        return False
    return isinstance(decision, bool) and decision


def can_author_course(actor, course: Course | None) -> bool:
    """Whether an actor may author reusable content for a course.

    ``course=None`` means authoring outside any course, which any authenticated
    teacher may do.
    """
    if not can_teach(actor):
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
    if not can_teach(actor):
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
    if not can_teach(actor):
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


def can_use_flow(actor, flow: Flow) -> bool:
    """A share grants use and copying, never authoring or access to session data."""
    if not can_teach(actor):
        return False
    if can_edit_flow(actor, flow) or flow.shares.filter(user=actor).exists():
        return True
    from .demos import is_public_demo_flow

    return is_public_demo_flow(flow)


def can_read_asset(actor, asset) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    if actor.is_superuser or asset.owner_id == actor.pk:
        return True
    # A public demo is common course material, but hosts still expose it only
    # to accounts that pass their teacher policy.  This makes file previews in
    # the shared lesson usable without granting an ordinary student library
    # access to the seed account's asset.
    if can_teach(actor) and Flow.objects.filter(
        demo_lesson__is_public=True,
        steps__activity_definition__asset=asset,
    ).exists():
        return True
    # A retained copy explicitly owns its content reference; sharing exposes
    # only assets actually used by the selected lesson.
    if asset.activity_definitions.filter(owner=actor).exists():
        return True
    from django.db.models import Q
    return Flow.objects.filter(steps__activity_definition__asset=asset).filter(
        Q(created_by=actor) | Q(shares__user=actor) | Q(course__created_by=actor)
        | Q(course__memberships__user=actor, course__memberships__role__in=["teacher", "assistant"])
    ).exists()
