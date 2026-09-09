"""Bounded recovery command for submitted attempts without automatic grades."""

from django.core.management.base import BaseCommand, CommandError

from liveclassroom.services.assessment_grading import grade_pending_attempts
from liveclassroom.services.classroom import ClassroomError


class Command(BaseCommand):
    help = (
        "Grade submitted assessment attempts that have no durable result. "
        "Hosts may run this command from an existing scheduler."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum submitted attempts to inspect (default: 500).",
        )

    def handle(self, *args, **options):
        try:
            counts = grade_pending_attempts(limit=options["limit"])
        except ClassroomError as exc:
            raise CommandError(str(exc)) from exc
        summary = " ".join(f"{key}={value}" for key, value in counts.items())
        self.stdout.write(summary)
        if counts["failed"]:
            raise CommandError(f"Automatic grading completed with failures: {summary}")
