from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.views.generic import FormView, TemplateView

from .forms import CreateSessionForm, JoinSessionForm
from .models import LiveSession
from .services.classroom import can_manage_session


class HomeView(TemplateView):
    template_name = "liveclassroom/home.html"


class TeacherDashboardView(LoginRequiredMixin, FormView):
    template_name = "liveclassroom/teacher_dashboard.html"
    form_class = CreateSessionForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        session = form.save()
        return redirect("liveclassroom:teacher-console", session_id=session.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sessions"] = LiveSession.objects.filter(teacher=self.request.user).select_related("course", "flow")
        return context


class TeacherConsoleView(LoginRequiredMixin, TemplateView):
    template_name = "liveclassroom/teacher_console.html"

    def dispatch(self, request, *args, **kwargs):
        self.session = LiveSession.objects.select_related("course", "flow").get(pk=kwargs["session_id"])
        if not can_manage_session(request.user, self.session):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session"] = self.session
        context["items"] = self.session.flow.items.select_related("question").all()
        return context


class JoinView(FormView):
    template_name = "liveclassroom/join.html"
    form_class = JoinSessionForm

    def form_valid(self, form):
        session = LiveSession.objects.filter(join_code__iexact=form.cleaned_data["join_code"]).first()
        if not session:
            form.add_error("join_code", "No classroom exists with this code.")
            return self.form_invalid(form)
        self.request.session[f"liveclassroom.pending_name.{session.id}"] = form.cleaned_data["display_name"]
        return redirect("liveclassroom:student-session", session_id=session.id)


class StudentSessionView(TemplateView):
    template_name = "liveclassroom/student_session.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = LiveSession.objects.get(pk=kwargs["session_id"])
        context["session"] = session
        context["pending_name"] = self.request.session.get(f"liveclassroom.pending_name.{session.id}")
        return context


def health(request):
    """A dependency-free endpoint for deployment health checks."""
    return JsonResponse({"status": "ok", "service": "liveclassroom"})
