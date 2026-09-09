"""Bounded recovery command for server-expired assessment attempts."""

from django.core.management.base import BaseCommand, CommandError

from liveclassroom.services.assessment_timing import expire_due_attempts
from liveclassroom.services.classroom import ClassroomError


class Command(BaseCommand):
    help = (
        "Finalize due assessment attempts without a connected browser. "
        "Hosts may run this command every minute (for example, with cron or systemd)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Maximum due attempts to inspect in this invocation (default: 500).",
        )

    def handle(self, *args, **options):
        try:
            counts = expire_due_attempts(limit=options["limit"])
        except ClassroomError as exc:
            raise CommandError(str(exc)) from exc
        summary = " ".join(f"{key}={value}" for key, value in counts.items())
        self.stdout.write(summary)
        if counts["failed"]:
            raise CommandError(f"Assessment expiry completed with failures: {summary}")
