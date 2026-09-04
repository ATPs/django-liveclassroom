import qrcode
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import FormView, TemplateView
from qrcode.image.svg import SvgPathImage

from .conf import base_template, websocket_path
from .forms import CreateSessionForm, JoinSessionForm
from .models import LiveSession
from .services.classroom import can_manage_session, can_view_display


class LocaleContextMixin:
    """Provide active_lang context to templates based on ?lang=, session, or default."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lang = self.request.GET.get("lang")
        if not lang and hasattr(self.request, "LANGUAGE_CODE"):
            lang = self.request.LANGUAGE_CODE
        context["active_lang"] = lang or "en"
        context["liveclassroom_base_template"] = base_template()
        return context


class HomeView(LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/home.html"


class TeacherDashboardView(LoginRequiredMixin, LocaleContextMixin, FormView):
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


class TeacherConsoleView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/teacher_console.html"

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(LiveSession.objects.select_related("course", "flow"), pk=kwargs["session_id"])
        if not can_manage_session(request.user, self.session):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session"] = self.session
        context["websocket_url"] = websocket_path(self.session.id)
        context["steps"] = (
            self.session.flow.steps.select_related("activity_definition").all() if self.session.flow_id else []
        )
        return context


class ClassroomDisplayView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    """Render a restricted projector surface for a teacher, co-host, or observer."""

    template_name = "liveclassroom/classroom_display.html"

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(LiveSession, pk=kwargs["session_id"])
        if not can_view_display(request.user, self.session):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session"] = self.session
        context["websocket_url"] = websocket_path(self.session.id)
        return context


class JoinView(LocaleContextMixin, FormView):
    template_name = "liveclassroom/join.html"
    form_class = JoinSessionForm

    def get_initial(self):
        initial = super().get_initial()
        code = self.request.GET.get("code", "").strip()
        if code:
            initial["join_code"] = code
        return initial

    def form_valid(self, form):
        session = LiveSession.objects.filter(join_code__iexact=form.cleaned_data["join_code"]).first()
        if not session:
            form.add_error("join_code", "No classroom exists with this code.")
            return self.form_invalid(form)
        self.request.session[f"liveclassroom.pending_name.{session.id}"] = form.cleaned_data["display_name"]
        return redirect("liveclassroom:student-session", session_id=session.id)


class StudentSessionView(LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/student_session.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = get_object_or_404(LiveSession, pk=kwargs["session_id"])
        context["session"] = session
        context["pending_name"] = self.request.session.get(f"liveclassroom.pending_name.{session.id}")
        context["websocket_url"] = websocket_path(session.id)
        return context


def join_qr(request, session_id: int):
    """Render an authenticated teacher's join URL as a self-contained SVG QR code."""
    session = get_object_or_404(LiveSession, pk=session_id)
    if not can_manage_session(request.user, session):
        raise Http404
    join_url = request.build_absolute_uri(f"{reverse('liveclassroom:join')}?code={session.join_code}")
    code = qrcode.QRCode(border=2, box_size=8)
    code.add_data(join_url)
    code.make(fit=True)
    svg = code.make_image(image_factory=SvgPathImage).to_string(encoding="unicode")
    response = HttpResponse(svg, content_type="image/svg+xml; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    return response


class FlowBuilderView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/builder.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flow_id = kwargs.get("flow_id")
        if flow_id:
            context["flow_id"] = flow_id
        session_id = kwargs.get("session_id") or self.request.GET.get("session_id")
        if session_id:
            try:
                context["session_id"] = int(session_id)
            except (TypeError, ValueError):
                pass
        return context


def health(request):
    """A dependency-free endpoint for deployment health checks."""
    return JsonResponse({"status": "ok", "service": "liveclassroom"})
