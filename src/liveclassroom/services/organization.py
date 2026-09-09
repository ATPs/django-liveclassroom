"""Optional subject/program organization for existing classroom cohorts."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from liveclassroom.models import Course, TeachingCourse

from .permissions import can_teach


class OrganizationConflict(Exception):
    """Raised when a requested association contradicts the current grouping."""


def _require_teacher(actor) -> None:
    if not can_teach(actor):
        raise PermissionDenied("Teacher access is required.")


def _require_management(actor, teaching_course: TeachingCourse) -> None:
    _require_teacher(actor)
    if getattr(actor, "is_superuser", False) or teaching_course.created_by_id == actor.pk:
        return
    raise PermissionDenied("You do not have permission to manage this teaching course.")


def _require_cohort_management(actor, cohort: Course) -> None:
    _require_teacher(actor)
    if getattr(actor, "is_superuser", False) or cohort.created_by_id == actor.pk:
        return
    raise PermissionDenied("You do not have permission to manage this class.")


def _title(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("A teaching course title of at most 200 characters is required.")
    value = value.strip()
    if not value or len(value) > 200:
        raise ValidationError("A teaching course title of at most 200 characters is required.")
    return value


def _description(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("Description must be a string.")
    return value


def _same_owner(teaching_course: TeachingCourse, cohort: Course) -> None:
    if teaching_course.created_by_id != cohort.created_by_id:
        raise ValidationError("A class and teaching course must have the same owner.")


def list_teaching_courses(*, actor):
    """Return the actor's own groupings, or all groupings for a superuser."""
    _require_teacher(actor)
    if getattr(actor, "is_superuser", False):
        return TeachingCourse.objects.all()
    return TeachingCourse.objects.filter(created_by=actor)


def create_teaching_course(*, actor, title, description="") -> TeachingCourse:
    _require_teacher(actor)
    title = _title(title)
    description = _description(description)
    with transaction.atomic():
        return TeachingCourse.objects.create(title=title, description=description, created_by=actor)


def update_teaching_course(*, actor, teaching_course, changes) -> TeachingCourse:
    _require_teacher(actor)
    if not isinstance(changes, dict) or set(changes) - {"title", "description"}:
        raise ValidationError("Only title and description may be changed.")
    values = {}
    if "title" in changes:
        values["title"] = _title(changes["title"])
    if "description" in changes:
        values["description"] = _description(changes["description"])
    with transaction.atomic():
        teaching_course = TeachingCourse.objects.select_for_update().get(pk=teaching_course.pk)
        _require_management(actor, teaching_course)
        if values:
            for field, value in values.items():
                setattr(teaching_course, field, value)
            teaching_course.save(update_fields=[*values, "updated_at"])
        return teaching_course


def delete_teaching_course(*, actor, teaching_course) -> None:
    with transaction.atomic():
        teaching_course = TeachingCourse.objects.select_for_update().get(pk=teaching_course.pk)
        _require_management(actor, teaching_course)
        list(Course.objects.select_for_update().filter(teaching_course=teaching_course).only("pk"))
        teaching_course.delete()


def assign_class(*, actor, teaching_course, cohort) -> Course:
    """Associate a cohort with a same-owner grouping, moving it if necessary."""
    with transaction.atomic():
        teaching_course = TeachingCourse.objects.select_for_update().get(pk=teaching_course.pk)
        cohort = Course.objects.select_for_update().get(pk=cohort.pk)
        _require_management(actor, teaching_course)
        _require_cohort_management(actor, cohort)
        _same_owner(teaching_course, cohort)
        if cohort.teaching_course_id != teaching_course.pk:
            cohort.teaching_course = teaching_course
            cohort.save(update_fields=["teaching_course", "updated_at"])
        return cohort


def unassign_class(*, actor, teaching_course, cohort) -> Course:
    """Detach a cohort, unless the supplied grouping conflicts with its current one."""
    with transaction.atomic():
        teaching_course = TeachingCourse.objects.select_for_update().get(pk=teaching_course.pk)
        cohort = Course.objects.select_for_update().get(pk=cohort.pk)
        _require_management(actor, teaching_course)
        _require_cohort_management(actor, cohort)
        _same_owner(teaching_course, cohort)
        if cohort.teaching_course_id is None:
            return cohort
        if cohort.teaching_course_id != teaching_course.pk:
            raise OrganizationConflict("This class belongs to another teaching course.")
        cohort.teaching_course = None
        cohort.save(update_fields=["teaching_course", "updated_at"])
        return cohort
