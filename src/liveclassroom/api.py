import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import FlowItem, LiveActivity, LiveSession, Participant
from .services.classroom import (
    ClassroomError,
    can_manage_session,
    join_guest,
    launch_item,
    result_summary,
    set_activity_state,
    start_session,
    submit_answer,
)


def _body(request) -> dict:
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        raise ClassroomError("Request body must be valid JSON.")


def _error(message: str, status: int = 400):
    return JsonResponse({"detail": message}, status=status)


def _participant_for_request(request, session: LiveSession) -> Participant | None:
    participant_id = request.session.get(f"liveclassroom.participant.{session.id}")
    if participant_id:
        return Participant.objects.filter(pk=participant_id, session=session).first()
    if request.user.is_authenticated:
        return Participant.objects.filter(session=session, user=request.user).first()
    return None


def _public_activity(activity: LiveActivity | None) -> dict | None:
    if not activity:
        return None
    snapshot = activity.definition_snapshot.copy()
    question = snapshot.get("question")
    if question and activity.state != LiveActivity.State.REVEALED:
        question = question.copy()
        question.pop("answer", None)
        question.pop("explanation_markdown", None)
        snapshot["question"] = question
    return {"id": activity.id, "state": activity.state, "definition": snapshot}


@require_POST
def start(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    try:
        start_session(session=session, actor=request.user)
    except ClassroomError as exc:
        return _error(str(exc), 403)
    return JsonResponse({"id": session.id, "status": session.status, "version": session.state_version})


@require_POST
def launch(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    try:
        item = get_object_or_404(FlowItem, pk=_body(request)["flow_item_id"])
        activity = launch_item(session=session, item=item, actor=request.user)
    except KeyError:
        return _error("flow_item_id is required.")
    except ClassroomError as exc:
        return _error(str(exc), 403)
    return JsonResponse({"activity_id": activity.id, "version": session.state_version}, status=201)


@require_POST
def transition(request, activity_id: int, state: str):
    activity = get_object_or_404(LiveActivity, pk=activity_id)
    try:
        set_activity_state(activity=activity, state=state, actor=request.user)
    except ClassroomError as exc:
        return _error(str(exc), 403)
    return JsonResponse({"activity_id": activity.id, "state": activity.state})


@require_POST
def join(request, join_code: str):
    session = get_object_or_404(LiveSession, join_code__iexact=join_code)
    try:
        data = _body(request)
        display_name = data["display_name"].strip()
        if not display_name:
            raise ClassroomError("Display name is required.")
        guest_id = request.session.get(f"liveclassroom.guest.{session.id}")
        participant = join_guest(session=session, display_name=display_name, guest_id=guest_id)
    except KeyError:
        return _error("display_name is required.")
    except ClassroomError as exc:
        return _error(str(exc))
    request.session[f"liveclassroom.guest.{session.id}"] = participant.guest_id
    request.session[f"liveclassroom.participant.{session.id}"] = participant.id
    return JsonResponse({"session_id": session.id, "participant_id": participant.id}, status=201)


@require_GET
def state(request, session_id: int):
    session = get_object_or_404(LiveSession, pk=session_id)
    activity = session.activities.order_by("-sequence").first()
    participant = _participant_for_request(request, session)
    submission = None
    if participant and activity:
        submission = activity.submissions.filter(participant=participant).values("id", "answer").first()
    return JsonResponse(
        {
            "session": {"id": session.id, "status": session.status, "version": session.state_version},
            "current_activity": _public_activity(activity),
            "my_submission": submission,
        }
    )


@require_POST
def submit(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    participant = _participant_for_request(request, activity.session)
    if not participant:
        return _error("Join the classroom before submitting.", 403)
    try:
        submission = submit_answer(activity=activity, participant=participant, answer=_body(request).get("answer", {}))
    except ClassroomError as exc:
        return _error(str(exc), 409)
    return JsonResponse({"submission_id": submission.id}, status=201)


@require_GET
def results(request, activity_id: int):
    activity = get_object_or_404(LiveActivity.objects.select_related("session"), pk=activity_id)
    if not can_manage_session(request.user, activity.session):
        return _error("You do not have permission to view results.", 403)
    return JsonResponse(result_summary(activity))
