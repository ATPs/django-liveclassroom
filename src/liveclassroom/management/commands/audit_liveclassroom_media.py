from django.core.management.base import BaseCommand

from liveclassroom.models import ActivityDefinition, FlowItem, FlowStep, LiveActivity
from liveclassroom.services.classroom import validate_activity_snapshot

_LEGACY_MEDIA_KINDS = frozenset({"image", "video", "url", "iframe"})


def _snapshot_for_row(row) -> dict:
    if isinstance(row, ActivityDefinition):
        return {"type_key": row.type_key, "content": row.definition}
    return {"kind": row.kind, "title": row.title, "content": row.content}


class Command(BaseCommand):
    help = "Report stored LiveClassroom media that fails the current safety policy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Disable unsafe rows after reporting them; never rewrite a URL into a different URL.",
        )

    def handle(self, *args, **options):
        findings: list[tuple[str, int, str, object]] = []

        definitions = ActivityDefinition.objects.filter(type_key="liveclassroom.media").only(
            "id", "type_key", "definition"
        )
        for row in definitions:
            try:
                validate_activity_snapshot(_snapshot_for_row(row))
            except (KeyError, TypeError, ValueError) as exc:
                findings.append(("ActivityDefinition", row.id, str(exc), row))

        for model in (FlowItem, FlowStep):
            queryset = model.objects.filter(kind__in=_LEGACY_MEDIA_KINDS).only("id", "kind", "title", "content")
            for row in queryset:
                try:
                    validate_activity_snapshot(_snapshot_for_row(row))
                except (KeyError, TypeError, ValueError) as exc:
                    findings.append((model.__name__, row.id, str(exc), row))

        for row in LiveActivity.objects.only("id", "kind", "definition_snapshot"):
            snapshot = row.definition_snapshot
            if row.kind not in _LEGACY_MEDIA_KINDS and not (
                isinstance(snapshot, dict) and snapshot.get("type_key") == "liveclassroom.media"
            ):
                continue
            try:
                validate_activity_snapshot(snapshot)
            except (KeyError, TypeError, ValueError) as exc:
                findings.append(("LiveActivity", row.id, str(exc), row))

        if not findings:
            self.stdout.write("No unsafe stored media found.")
            return

        for model_name, row_id, error, _row in findings:
            self.stdout.write(f"{model_name} {row_id}: {error}")

        if not options["repair"]:
            self.stdout.write(self.style.WARNING("Report only; pass --repair to disable these rows."))
            return

        repaired = 0
        for model_name, _row_id, _error, row in findings:
            if model_name == "ActivityDefinition":
                repaired += ActivityDefinition.objects.filter(pk=row.pk).update(
                    status=ActivityDefinition.Status.ARCHIVED
                )
            elif model_name in {"FlowItem", "FlowStep"}:
                repaired += type(row).objects.filter(pk=row.pk).update(
                    content={"media_disabled": True, "disabled_reason": "unsafe_media"}
                )
            else:
                snapshot = row.definition_snapshot if isinstance(row.definition_snapshot, dict) else {}
                repaired += LiveActivity.objects.filter(pk=row.pk).update(
                    definition_snapshot={
                        "schema_version": snapshot.get("schema_version", 1),
                        "type_key": "liveclassroom.media",
                        "kind": "media",
                        "title": snapshot.get("title", ""),
                        "content": {"media_disabled": True, "disabled_reason": "unsafe_media"},
                        "media_disabled": True,
                    }
                )
        self.stdout.write(self.style.SUCCESS(f"Disabled {repaired} unsafe stored media row(s)."))
