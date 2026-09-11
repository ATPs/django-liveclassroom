"""Authorized server-rendered session lists with durable browse state."""

from django.core.paginator import Paginator
from django.db.models import Q

from .models import Course, CourseMembership, LiveSession
from .services.classroom import can_view_session


def session_list_context(request, *, preview=False):
    actor = request.user
    staff_courses = Course.objects.filter(
        Q(created_by=actor) | Q(memberships__user=actor, memberships__role__in=[
            CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT,
        ])
    ).distinct()
    rows = LiveSession.objects.select_related("course").all()
    if not actor.is_superuser:
        rows = rows.filter(Q(teacher=actor) | Q(course__in=staff_courses)).distinct()
    if preview:
        rows = rows.exclude(status=LiveSession.Status.ENDED)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if query:
        rows = rows.filter(title__icontains=query)
    if status in LiveSession.Status.values:
        rows = rows.filter(status=status)
    else:
        status = ""
    sort = request.GET.get("sort", "recent")
    if sort not in {"recent", "title"}:
        sort = "recent"
    rows = rows.order_by("title" if sort == "title" else "-updated_at", "id")
    visible = [row for row in rows if can_view_session(actor, row)]
    page = Paginator(visible, 25).get_page(request.GET.get("page"))

    def destination(number):
        params = request.GET.copy()
        params["page"] = str(number)
        return f"{request.path}?{params.urlencode()}"

    return {
        "sessions": page.object_list, "session_page": page,
        "previous_url": destination(page.previous_page_number()) if page.has_previous() else "",
        "next_url": destination(page.next_page_number()) if page.has_next() else "",
        "browse_q": query, "browse_sort": sort, "browse_status": status,
        "session_statuses": LiveSession.Status.choices,
    }
