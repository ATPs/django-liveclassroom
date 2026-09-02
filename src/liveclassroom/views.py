from django.http import JsonResponse
from django.views.generic import TemplateView


class HomeView(TemplateView):
    template_name = "liveclassroom/home.html"


class TeacherConsoleView(TemplateView):
    template_name = "liveclassroom/teacher_console.html"


class JoinView(TemplateView):
    template_name = "liveclassroom/join.html"


def health(request):
    """A dependency-free endpoint for deployment health checks."""
    return JsonResponse({"status": "ok", "service": "liveclassroom"})
