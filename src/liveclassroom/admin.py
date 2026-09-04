from django.contrib import admin

from .models import (
    ActivityDefinition,
    ActivityDefinitionRevision,
    AuthoringAttachment,
    AuthoringJob,
    AuthoringMessage,
    AuthoringThread,
    CommandReceipt,
    Course,
    CourseMembership,
    Flow,
    LiveActivity,
    LiveSession,
    Participant,
    SessionChannelState,
    SessionEvent,
    SessionMessage,
    SessionStaff,
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


@admin.register(ActivityDefinition)
class ActivityDefinitionAdmin(admin.ModelAdmin):
    list_display = ("title", "type_key", "owner", "course", "status", "updated_at")
    list_filter = ("type_key", "status", "course")
    search_fields = ("title", "type_key")


@admin.register(ActivityDefinitionRevision)
class ActivityDefinitionRevisionAdmin(admin.ModelAdmin):
    list_display = ("definition", "revision", "changed_by", "created_at")
    list_filter = ("schema_version",)


@admin.register(LiveSession)
class LiveSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "flow", "join_code", "status", "archived_at", "state_version")
    list_filter = ("status", "access_mode", "admission_mode", "course")
    search_fields = ("title", "join_code", "course__title")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("display_name", "session", "user", "joined_at", "last_seen_at")
    search_fields = ("display_name", "guest_id", "user__username")


admin.site.register(LiveActivity)
admin.site.register(Submission)
admin.site.register(SessionEvent)
admin.site.register(SessionMessage)
admin.site.register(CommandReceipt)
admin.site.register(SessionChannelState)
admin.site.register(SessionStaff)
admin.site.register(AuthoringThread)
admin.site.register(AuthoringMessage)
admin.site.register(AuthoringAttachment)
admin.site.register(AuthoringJob)
