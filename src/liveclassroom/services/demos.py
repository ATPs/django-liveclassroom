"""Queries for the common, read-only teaching examples."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from liveclassroom.models import DemoLesson, Flow, LiveSession


def public_demo_lessons() -> QuerySet[DemoLesson]:
    return DemoLesson.objects.filter(is_public=True)


def public_demo_flows() -> QuerySet[Flow]:
    return Flow.objects.filter(demo_lesson__is_public=True)


def public_demo_sessions() -> QuerySet[LiveSession]:
    return LiveSession.objects.filter(
        Q(demo_ready_for__is_public=True)
        | Q(demo_live_for__is_public=True)
        | Q(demo_ended_for__is_public=True)
    ).distinct()


def is_public_demo_flow(flow: Flow) -> bool:
    return public_demo_lessons().filter(flow_id=flow.pk).exists()


def is_public_demo_session(session: LiveSession) -> bool:
    return public_demo_lessons().filter(
        ready_session_id=session.pk,
    ).exists() or public_demo_lessons().filter(live_session_id=session.pk).exists() or public_demo_lessons().filter(
        ended_session_id=session.pk
    ).exists()
