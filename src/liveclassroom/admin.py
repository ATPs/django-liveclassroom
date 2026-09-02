from django.contrib import admin

from .models import (
    Course,
    CourseMembership,
    Flow,
    FlowItem,
    LiveActivity,
    LiveSession,
    Participant,
    Question,
    SessionEvent,
    Submission,
)


class CourseMembershipInline(admin.TabularInline):
    model = CourseMembership
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "created_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [CourseMembershipInline]


@admin.register(Flow)
class FlowAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "slug", "updated_at")
    list_filter = ("course",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(FlowItem)
class FlowItemAdmin(admin.ModelAdmin):
    list_display = ("flow", "position", "kind", "title", "question")
    list_filter = ("kind", "flow__course")
    ordering = ("flow", "position")


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("id", "question_type", "status", "difficulty", "updated_at")
    list_filter = ("question_type", "status")
    search_fields = ("stem_markdown", "source")


@admin.register(LiveSession)
class LiveSessionAdmin(admin.ModelAdmin):
    list_display = ("course", "flow", "join_code", "status", "mode", "state_version")
    list_filter = ("status", "mode", "course")
    search_fields = ("join_code", "course__title")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "session", "role", "user", "joined_at", "last_seen_at")
    list_filter = ("role",)
    search_fields = ("display_name", "guest_id", "user__username")


admin.site.register(LiveActivity)
admin.site.register(Submission)
admin.site.register(SessionEvent)
