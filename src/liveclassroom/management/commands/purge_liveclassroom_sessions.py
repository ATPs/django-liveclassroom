from django.core.management.base import BaseCommand, CommandError

from liveclassroom.services.classroom import ClassroomError, purge_expired_sessions


class Command(BaseCommand):
    help = "Delete ended LiveClassroom sessions older than the configured retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            help="Override LIVECLASSROOM['RETENTION_DAYS'] for this run.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Required for non-interactive scheduled execution.",
        )

    def handle(self, *args, **options):
        if not options["no_input"]:
            raise CommandError("Pass --no-input to run retention cleanup explicitly.")
        try:
            deleted = purge_expired_sessions(days=options.get("days"))
        except ClassroomError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired LiveClassroom session record(s)."))
