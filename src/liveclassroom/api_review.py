"""Student activity review and per-activity review access APIs."""

from types import SimpleNamespace

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .api import (
    _act_as_context,
    _body,
    _error,
    _participant_for_request,
    _public_activity,
    _record,
    _replay,
)
from .models import LiveActivity, LiveSession, Participant
from .services.classroom import (
    ClassroomError,
    _advance_version,
    _append_event,
    can_manage_session,
    can_view_session,
)
from .services.events import notify_session_after_commit

_REVIEW_FIELDS = frozenset({"reviewable", "show_answer", "show_explanation"})


def _visibility(activity: LiveActivity) -> dict[str, bool]:
    raw = activity.review_visibility
    return {
        "show_answer": isinstance(raw, dict) and raw.get("show_answer") is True,
        "show_explanation": isinstance(raw, dict) and raw.get("show_explanation") is True,
    }


def _review_channel(activity: LiveActivity, visibility: dict[str, bool]):
    """Adapt per-activity review flags to the public activity serializer."""
    return SimpleNamespace(
        current_activity_id=activity.id,
        current_revision=activity.current_revision,
        show_prompt=True,
        show_answer=visibility["show_answer"],
        show_explanation=visibility["show_explanation"],
    )


def _history_activity(activity: LiveActivity, *, staff_view: bool, request, session: LiveSession) -> dict:
    visibility = _visibility(activity)
    effective_visibility = {
        "show_answer": True,
        "show_explanation": True,
    } if staff_view else visibility
    result = _public_activity(
        activity,
        channel_state=_review_channel(activity, effective_visibility),
        request=request,
        session=session,
        force_show_prompt=True,
    )
    if staff_view:
        result["reviewable"] = activity.reviewable
        result["review_visibility"] = visibility
    return result


@require_GET
def history(request, session_id: int):
    """Return the session history allowed for this participant or staff user."""
    session = get_object_or_404(LiveSession, pk=session_id)
    try:
        act_as_participant, _active = _act_as_context(request, session)
    except ClassroomError as exc:
        return _error(str(exc), 403)

    acting_as = act_as_participant is not None
    participant = act_as_participant or _participant_for_request(request, session)
    staff_view = not acting_as and can_view_session(request.user, session)
    if not staff_view:
        if participant is None:
            return _error("Join the classroom before viewing activity history.", 403)
        if participant.admission_state != Participant.AdmissionState.ADMITTED:
            return _error("You are not admitted to this classroom.", 403)

    activities = session.activities.order_by("sequence", "id").select_related(
        "current_revision", "current_revision__asset"
    )
    if not staff_view:
        activities = activities.filter(reviewable=True)

    payload = []
    for activity in activities:
        item = _history_activity(activity, staff_view=staff_view, request=request, session=session)
        if participant is not None and not staff_view:
            item["own_submission"] = activity.submissions.filter(participant_id=participant.id).values(
                "answer", "is_stale"
            ).first()
        payload.append(item)
    return JsonResponse({"session_id": session.id, "activities": payload})


@require_POST
@transaction.atomic
def review_settings(request, activity_id: int):
    """Update review access for one activity, including after session end."""
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    session = activity.session
    replay, key = _replay(request, session, "activity.review_settings")
    if replay is not None:
        return replay

    try:
        body = _body(request)
        unknown = set(body) - _REVIEW_FIELDS
        if unknown:
            raise ClassroomError(f"Unsupported review settings: {', '.join(sorted(unknown))}.")
        if not body:
            raise ClassroomError("At least one review setting is required.")
        for field, value in body.items():
            if not isinstance(value, bool):
                raise ClassroomError(f"{field} must be a boolean.")
        session = LiveSession.objects.select_for_update().get(pk=activity.session_id)
        activity = LiveActivity.objects.select_for_update().get(pk=activity.id, session=session)
        if not can_manage_session(request.user, session):
            return _record(
                session,
                key,
                "activity.review_settings",
                request,
                _error("You do not have permission to manage activity review.", 403),
            )

        visibility = _visibility(activity)
        update_fields = []
        if "reviewable" in body:
            activity.reviewable = body["reviewable"]
            update_fields.append("reviewable")
        for field in ("show_answer", "show_explanation"):
            if field in body:
                visibility[field] = body[field]
        if any(field in body for field in ("show_answer", "show_explanation")):
            activity.review_visibility = visibility
            update_fields.append("review_visibility")
        activity.save(update_fields=update_fields)

        version = _advance_version(session)
        event_payload = {
            "activity_id": activity.id,
            "reviewable": activity.reviewable,
            "review_visibility": visibility,
        }
        event_id = _append_event(session, "activity.review.updated", request.user, event_payload)
        notify_session_after_commit(
            session.id,
            {
                "protocol": 1,
                "session_id": session.id,
                "version": version,
                "event_id": event_id,
                "type": "activity.review.updated",
                "payload": event_payload,
            },
        )
        response = JsonResponse(
            {
                "session_id": session.id,
                "activity_id": activity.id,
                "version": version,
                "reviewable": activity.reviewable,
                "review_visibility": visibility,
            }
        )
    except ClassroomError as exc:
        return _record(session, key, "activity.review_settings", request, _error(str(exc)))
    return _record(session, key, "activity.review_settings", request, response)
