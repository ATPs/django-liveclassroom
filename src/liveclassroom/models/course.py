from django.conf import settings
from django.db import models


class Course(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="liveclassroom_courses_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title


class CourseMembership(models.Model):
    class Role(models.TextChoices):
        TEACHER = "teacher", "Teacher"
        ASSISTANT = "assistant", "Assistant"
        STUDENT = "student", "Student"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="liveclassroom_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "user"], name="lc_membership_once")]
        ordering = ["course", "user"]

    def __str__(self) -> str:
        return f"{self.user} — {self.course} ({self.role})"
