from django.apps import AppConfig


class LiveClassroomConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "liveclassroom"
    verbose_name = "Live classroom"

    def ready(self) -> None:
        import liveclassroom.checks  # noqa: F401
