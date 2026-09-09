import json

import qrcode
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, TemplateView
from qrcode.image.svg import SvgPathImage

from .conf import base_template, websocket_path
from .forms import CreateSessionForm, JoinSessionForm
from .models import LiveSession
from .services.classroom import can_manage_session, can_view_display, can_view_session, session_capabilities
from .services.permissions import can_teach
from .services.presentation import presentation_title


class LocaleContextMixin:
    """Provide active_lang context and active translation based on ?lang=."""

    def resolve_locale(self) -> str:
        def normalize(value) -> str | None:
            lang = str(value or "").strip().lower()
            if lang.startswith("zh"):
                return "zh-Hans"
            if lang.startswith("en"):
                return "en"
            return None

        for value in (
            self.request.GET.get("lang"),
            self.request.COOKIES.get("liveclassroom_locale"),
            getattr(self.request, "LANGUAGE_CODE", None),
        ):
            locale = normalize(value)
            if locale:
                return locale
        return "en"

    def dispatch(self, request, *args, **kwargs):
        # TemplateResponse renders lazily, so render inside the override to make
        # {% translate %} and lazy form labels resolve in the active locale.
        with translation.override(self.resolve_locale()):
            response = super().dispatch(request, *args, **kwargs)
            if hasattr(response, "render"):
                response.render()
            return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_lang"] = self.resolve_locale()
        context["liveclassroom_base_template"] = base_template()
        return context


class HomeView(LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/home.html"


class HelpView(LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/help.html"


class TeacherRequiredMixin(LoginRequiredMixin):
    """Require the optional host teacher policy after normal authentication."""

    def dispatch(self, request, *args, **kwargs):
        # Preserve Django's normal login redirect for anonymous visitors.  Once
        # authenticated, a host policy denial is intentionally a 403 rather
        # than a second login prompt.
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not can_teach(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class TeacherDashboardView(TeacherRequiredMixin, LocaleContextMixin, FormView):
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


class TeacherConsoleView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/teacher_console.html"

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(LiveSession.objects.select_related("course", "flow"), pk=kwargs["session_id"])
        if not can_view_session(request.user, self.session):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session"] = self.session
        context["websocket_url"] = websocket_path(self.session.id)
        steps = self.session.plan_steps.filter(removed=False)
        context["steps"] = steps
        context["flow_title"] = self.session.source_snapshot.title if self.session.source_snapshot_id else ""
        context["capabilities_json"] = json.dumps(session_capabilities(self.request.user, self.session))
        context["flow_steps_json"] = json.dumps(
            [
                {
                    "id": step.id,
                    "position": step.position,
                    "title": presentation_title(step.snapshot.get("title", "Activity")),
                }
                for step in steps
            ],
            ensure_ascii=False,
        )
        return context


class StudentView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """A staff-only participant-scoped student surface with no join side effects."""

    template_name = "liveclassroom/student_view.html"

    def dispatch(self, request, *args, **kwargs):
        self.session = get_object_or_404(LiveSession, pk=kwargs["session_id"])
        if not can_manage_session(request.user, self.session):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session"] = self.session
        context["websocket_url"] = websocket_path(self.session.id)
        return context


class ClassroomDisplayView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
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
            form.add_error("join_code", _("No classroom exists with this code."))
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


class FlowBuilderView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/builder.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flow_id = kwargs.get("flow_id") or self.request.GET.get("flow_id")
        if flow_id:
            from .models import Flow
            from .services.permissions import can_use_flow
            flow = get_object_or_404(Flow, pk=flow_id)
            if not can_use_flow(self.request.user, flow):
                raise Http404
            context["flow_id"] = flow.id
        session_id = kwargs.get("session_id") or self.request.GET.get("session_id")
        if session_id:
            try:
                context["session_id"] = int(session_id)
            except (TypeError, ValueError):
                pass
        return context


class DeckWorkspaceView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    template_name = "liveclassroom/decks.html"


def health(request):
    """A dependency-free endpoint for deployment health checks."""
    return JsonResponse({"status": "ok", "service": "liveclassroom"})
