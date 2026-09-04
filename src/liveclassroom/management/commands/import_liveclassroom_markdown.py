from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from liveclassroom.importers.markdown import ImportError, import_markdown_file
from liveclassroom.models import Course


class Command(BaseCommand):
    help = "Import a Markdown/YAML course flow into an existing course."

    def add_arguments(self, parser):
        parser.add_argument("course_slug")
        parser.add_argument("path", type=Path)
        parser.add_argument("--slug", help="Override the flow slug from front matter.")

    def handle(self, *args, **options):
        course = Course.objects.filter(slug=options["course_slug"]).first()
        if not course:
            raise CommandError(f"No course exists with slug {options['course_slug']!r}.")
        try:
            flow = import_markdown_file(course=course, path=options["path"], fallback_slug=options["slug"])
        except (OSError, ImportError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Imported {flow.steps.count()} steps into {flow}."))
