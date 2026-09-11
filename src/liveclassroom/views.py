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
from .models import AssessmentAttempt, AssessmentDefinition, AssessmentRun, Course, Deck, LiveSession
from .services.classroom import can_manage_session, can_view_display, can_view_session, session_capabilities
from .services.permissions import can_author_course, can_teach
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
        context["workspace_tab"] = kwargs.get("workspace_tab", "lessons")
        context["course_id"] = kwargs.get("course_id")
        return context


class TeachingCoursesView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Course-first teacher navigation backed by read-only browse summaries."""

    template_name = "liveclassroom/teaching_courses.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if kwargs.get("course_id") is not None:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-teaching-course", args=[kwargs["course_id"]])
        elif kwargs.get("class_id") is not None:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-teaching-class", args=[kwargs["class_id"]])
        else:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-teaching")
        context["teacher_url"] = reverse("liveclassroom:teacher-dashboard")
        return context


class QuestionBankView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Standalone Library destination for reusable question banks."""

    template_name = "liveclassroom/question_banks.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["api_root"] = reverse("liveclassroom:api-v1-workspace")
        return context


class ClassResultsView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Addressable class result page backed by the existing grade summary API."""

    template_name = "liveclassroom/class_results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        class_id = kwargs["class_id"]
        course_id = kwargs.get("course_id")
        course = get_object_or_404(Course, pk=class_id)
        if course_id is not None and course.teaching_course_id != course_id:
            raise Http404
        if not can_author_course(self.request.user, course):
            raise Http404
        context["summary_url"] = reverse("liveclassroom:api-v1-class-grade-summary", args=[class_id])
        context["parent_url"] = reverse("liveclassroom:teacher-class-detail", args=[class_id])
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        deck_id = kwargs.get("deck_id")
        if deck_id is not None and not Deck.objects.filter(pk=deck_id, owner=self.request.user).exists():
            raise Http404
        context["deck_id"] = deck_id
        return context


class AssessmentWorkspaceView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Teacher-only workspace for reusable assessment drafts."""

    template_name = "liveclassroom/assessments.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assessment_id = kwargs.get("assessment_id")
        if (
            assessment_id is not None
            and not AssessmentDefinition.objects.filter(pk=assessment_id, owner=self.request.user).exists()
        ):
            raise Http404
        context["assessment_id"] = assessment_id
        return context


class AssessmentAttemptView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    """Render the authenticated student entry point for one published run.

    The page itself does not create an attempt.  The React surface asks the
    authenticated attempt API to start or resume only after the student
    explicitly chooses that action.
    """

    template_name = "liveclassroom/assessment_attempt.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        run = get_object_or_404(AssessmentRun, public_id=kwargs["public_id"])
        context["run"] = run
        context["run_url"] = reverse("liveclassroom:api-v1-available-assessment-run", args=[run.public_id])
        context["start_url"] = reverse("liveclassroom:api-v1-assessment-attempts", args=[run.public_id])
        context["initial_attempt_id"] = ""
        return context


class LearningWorkspaceView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    """Course-first learner entry point; content arrives through scoped browse APIs."""

    template_name = "liveclassroom/learning.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if kwargs.get("course_id") is not None:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-learning-course", args=[kwargs["course_id"]])
        elif kwargs.get("class_id") is not None:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-learning-class", args=[kwargs["class_id"]])
        else:
            context["browse_url"] = reverse("liveclassroom:api-v1-browse-learning")
        context["join_url"] = reverse("liveclassroom:join")
        context["teacher_url"] = reverse("liveclassroom:teacher-dashboard") if can_teach(self.request.user) else ""
        return context


class LearningAttemptView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    """Address one existing attempt without creating or resuming a different one."""

    template_name = "liveclassroom/assessment_attempt.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            attempt = AssessmentAttempt.objects.select_related("run").get(
                public_id=kwargs["attempt_id"], user=self.request.user
            )
        except AssessmentAttempt.DoesNotExist as exc:
            raise Http404 from exc
        context["run"] = attempt.run
        context["run_url"] = reverse("liveclassroom:api-v1-available-assessment-run", args=[attempt.run.public_id])
        context["start_url"] = reverse("liveclassroom:api-v1-assessment-attempts", args=[attempt.run.public_id])
        context["initial_attempt_id"] = str(attempt.public_id)
        return context


def health(request):
    """A dependency-free endpoint for deployment health checks."""
    return JsonResponse({"status": "ok", "service": "liveclassroom"})
