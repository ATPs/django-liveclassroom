"""Explicit comparison and selective application of lesson/classroom changes."""

from copy import deepcopy

from django.db import transaction

from liveclassroom.models import ClassroomAsset, Flow, FlowStep, LiveSession, SessionPlanStep
from liveclassroom.services.classroom import ClassroomError, can_manage_session
from liveclassroom.services.permissions import can_edit_flow, can_use_flow

from .plans import (
    content_signature,
    copy_definition,
    fingerprint,
    flow_manifest,
    lock_plan,
    make_snapshot,
    plan_changed,
    session_manifest,
)


def _context(session, actor, direction):
    if not can_manage_session(actor, session):
        raise ClassroomError("You do not have permission to use this classroom.")
    if direction not in {"to_lesson", "to_session"}:
        raise ClassroomError("Unsupported comparison direction.")
    flow = session.flow
    if flow is None or not session.source_snapshot_id:
        raise ClassroomError("Save this classroom as a lesson first.")
    if direction == "to_lesson" and not can_edit_flow(actor, flow):
        raise ClassroomError("Only an author can update the original lesson; save your own copy instead.")
    if direction == "to_session" and not can_use_flow(actor, flow):
        raise ClassroomError("This lesson is no longer shared with you.")
    base = session.source_snapshot.manifest
    lesson = flow_manifest(flow)
    classroom = session_manifest(session)
    target, proposed = (lesson, classroom) if direction == "to_lesson" else (classroom, lesson)
    return flow, base, target, proposed


def compare_changes(*, session, actor, direction):
    session = LiveSession.objects.select_related("source_snapshot", "flow").get(pk=session.pk)
    flow, base, target, proposed = _context(session, actor, direction)
    before = {r["key"]: r for r in base}
    current = {r["key"]: r for r in target}
    desired = {r["key"]: r for r in proposed}
    launched = {str(k) for k in session.activities.exclude(plan_step=None).values_list("plan_step__key", flat=True)}
    changes = []
    for key in dict.fromkeys([r["key"] for r in proposed] + [r["key"] for r in base]):
        old, new, now = before.get(key), desired.get(key), current.get(key)
        if content_signature(old) == content_signature(new) or content_signature(now) == content_signature(new):
            continue
        if direction == "to_session" and key in launched:
            continue
        changes.append(
            {
                "key": key,
                "kind": "added" if old is None else "removed" if new is None else "modified",
                "title": (new or old)["snapshot"].get("title", "Activity"),
                "conflict": content_signature(now) != content_signature(old),
                "before": content_signature(now),
                "after": content_signature(new),
            }
        )
    base_order, target_order, proposed_order = ([r["key"] for r in rows] for rows in (base, target, proposed))
    if (
        proposed_order != base_order
        and proposed_order != target_order
        and not (direction == "to_session" and launched)
    ):
        changes.append(
            {
                "key": "__order__",
                "kind": "order",
                "title": "Step order",
                "conflict": target_order != base_order,
                "before": target_order,
                "after": proposed_order,
                "before_labels": [r["snapshot"].get("title", "Activity") for r in target],
                "after_labels": [r["snapshot"].get("title", "Activity") for r in proposed],
            }
        )
    token = fingerprint(
        {
            "flow_id": flow.pk,
            "base": base,
            "target": target,
            "proposed": proposed,
            "plan_version": session.plan_version,
            "direction": direction,
        }
    )
    return {"direction": direction, "token": token, "changes": changes, "flow_id": flow.pk}


def _merge_rows(target, proposed, keys):
    rows = {r["key"]: deepcopy(r) for r in target}
    new = {r["key"]: r for r in proposed}
    for key in keys:
        if key == "__order__":
            continue
        if key in new:
            rows[key] = deepcopy(new[key])
        else:
            rows.pop(key, None)
    order_source = proposed if "__order__" in keys else target
    order = [r["key"] for r in order_source if r["key"] in rows]
    order += [key for key in rows if key not in order]
    return [rows[key] for key in order]


@transaction.atomic
def apply_changes(*, session, actor, direction, token, keys, confirmed_conflicts=None):
    session = LiveSession.objects.select_for_update().get(pk=session.pk)
    if direction == "to_session":
        session = lock_plan(session, actor)
    if session.flow_id:
        # Refetch under the authoring lock before computing the comparison token.
        session.flow = Flow.objects.select_for_update().get(pk=session.flow_id)
    comparison = compare_changes(session=session, actor=actor, direction=direction)
    if token != comparison["token"]:
        raise ClassroomError("The content changed; refresh and compare again.")
    changes = {r["key"]: r for r in comparison["changes"]}
    if not isinstance(keys, list) or not keys or len(keys) != len(set(keys)) or not set(keys) <= set(changes):
        raise ClassroomError("Select changes from the current comparison.")
    conflicts = {key for key in keys if changes[key]["conflict"]}
    if not conflicts <= set(confirmed_conflicts or []):
        raise ClassroomError("Confirm conflicting changes explicitly before replacing them.")
    flow, base, target, proposed = _context(session, actor, direction)
    merged = _merge_rows(target, proposed, keys)
    if direction == "to_lesson":
        existing = {str(s.key): s for s in flow.steps.select_for_update().order_by("position")}
        retained_keys = {row["key"] for row in merged}
        removed_keys = set(existing) - retained_keys
        if removed_keys:
            FlowStep.objects.filter(flow=flow, key__in=removed_keys).delete()
        retained_steps = [existing[key] for key in retained_keys if key in existing]
        temporary_base = max(len(merged), max((step.position for step in retained_steps), default=0)) + 1
        for offset, step in enumerate(retained_steps, 1):
            step.position = temporary_base + offset
            step.save(update_fields=["position", "updated_at"])
        selected_content_keys = set(keys) - {"__order__"}
        for position, row in enumerate(merged, 1):
            old = existing.get(row["key"])
            if old:
                if row["key"] in selected_content_keys:
                    asset = ClassroomAsset.objects.filter(pk=row["asset_id"]).first() if row["asset_id"] else None
                    old.activity_definition = copy_definition(
                        actor=actor,
                        snapshot=row["snapshot"],
                        asset=asset,
                        course=flow.course,
                    )
                old.position = position
                old.save(update_fields=["position", "activity_definition", "updated_at"])
            else:
                asset = ClassroomAsset.objects.filter(pk=row["asset_id"]).first() if row["asset_id"] else None
                definition = copy_definition(actor=actor, snapshot=row["snapshot"], asset=asset, course=flow.course)
                FlowStep.objects.create(flow=flow, key=row["key"], position=position, activity_definition=definition)
        flow.save(update_fields=["updated_at"])
    else:
        retained = {r["key"] for r in merged}
        session.plan_steps.exclude(key__in=retained).update(removed=True)
        for position, row in enumerate(merged, 1):
            SessionPlanStep.objects.update_or_create(
                session=session,
                key=row["key"],
                defaults={
                    "position": position,
                    "snapshot": row["snapshot"],
                    "asset_id": row.get("asset_id"),
                    "removed": False,
                },
            )
    baseline = _merge_rows(base, proposed, keys)
    session.source_snapshot = make_snapshot(title=flow.title, manifest=baseline, flow=flow)
    session.save(update_fields=["source_snapshot"])
    plan_changed(session, actor, "plan.updated" if direction == "to_session" else "lesson.improvements.saved")
    return compare_changes(session=session, actor=actor, direction=direction)
