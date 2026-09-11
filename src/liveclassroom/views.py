import json

import qrcode
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, TemplateView
from qrcode.image.svg import SvgPathImage

from .conf import base_template, shell_links, websocket_path
from .forms import CreateSessionForm, JoinSessionForm
from .integrations.host import host_can_view_grade_summary
from .models import (
    AssessmentAttempt,
    AssessmentDefinition,
    AssessmentRun,
    Course,
    CourseMembership,
    Deck,
    Flow,
    LiveSession,
    TeachingCourse,
)
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
        context["classroom_shell"] = True
        context["navigation_bootstrap"] = self._navigation_bootstrap()
        return context

    def _navigation_bootstrap(self) -> dict:
        """Build non-secret, mount-safe data for the shared application shell."""
        actor = self.request.user
        authenticated = bool(getattr(actor, "is_authenticated", False))
        teacher_allowed = bool(authenticated and can_teach(actor))
        resolver = getattr(self.request, "resolver_match", None)
        view_name = resolver.view_name if resolver else ""
        path = self.request.path
        requested_mode = self.request.GET.get("mode")
        inferred_mode = (
            "learning"
            if view_name.startswith("liveclassroom:learn") or "assessment" in view_name
            else "teaching"
        )
        if view_name in {"liveclassroom:student-preview", "liveclassroom:student-view"}:
            inferred_mode = "student_preview"
        if requested_mode in {"teaching", "learning"}:
            inferred_mode = requested_mode
        if not authenticated:
            inferred_mode = "guest"
        elif inferred_mode in {"teaching", "student_preview"} and not teacher_allowed:
            inferred_mode = "learning"

        links = {
            "home": reverse("liveclassroom:home"),
            "join": reverse("liveclassroom:join"),
            "help": reverse("liveclassroom:help"),
            "learning": reverse("liveclassroom:learning-home"),
            "history": reverse("liveclassroom:assessment-history"),
            "browse_home": reverse("liveclassroom:api-v1-browse-home"),
            "navigation": reverse("liveclassroom:api-v1-browse-navigation"),
        }
        if teacher_allowed:
            links.update(
                {
                    "teacher": reverse("liveclassroom:teacher-dashboard"),
                    "courses": reverse("liveclassroom:teacher-courses"),
                    "classes": reverse("liveclassroom:teacher-classes"),
                    "sessions": reverse("liveclassroom:teacher-sessions"),
                    "results": reverse("liveclassroom:teacher-results"),
                    "lessons": reverse("liveclassroom:teacher-library-lessons"),
                    "decks": reverse("liveclassroom:teacher-library-decks"),
                    "assessments": reverse("liveclassroom:teacher-library-assessments"),
                    "questions": reverse("liveclassroom:teacher-library-questions"),
                    "shared": reverse("liveclassroom:teacher-library-shared"),
                    "student_preview": reverse("liveclassroom:student-preview"),
                }
            )

        current_context: dict[str, object] = {}
        class_id = self.kwargs.get("class_id")
        if class_id is not None:
            cohort = Course.objects.filter(pk=class_id).select_related("teaching_course").first()
            current_context = self._class_navigation_context(cohort, actor, authenticated, teacher_allowed)
        elif self.kwargs.get("course_id") is not None:
            teaching_course = TeachingCourse.objects.filter(pk=self.kwargs["course_id"]).first()
            current_context = self._course_navigation_context(teaching_course, actor, authenticated, teacher_allowed)
        else:
            cohort = self._object_context_course(actor)
            current_context = self._class_navigation_context(cohort, actor, authenticated, teacher_allowed)

        mount_path = reverse("liveclassroom:home")
        return {
            "locale": self.resolve_locale(),
            "mode": inferred_mode,
            "path": path,
            "authenticated": authenticated,
            "teacher_allowed": teacher_allowed,
            "user_label": getattr(actor, "get_username", lambda: "")() if authenticated else "",
            "preference_namespace": f"{mount_path}|{getattr(actor, 'pk', 'guest')}",
            "links": links,
            "host_links": shell_links(),
            "current_context": current_context,
            "current_ref": self._navigation_reference(view_name, resolver),
        }

    def _class_navigation_context(self, cohort, actor, authenticated, teacher_allowed) -> dict[str, object]:
        if cohort is None:
            return {}
        can_learn = bool(
            authenticated
            and CourseMembership.objects.filter(
                course=cohort, user=actor, role=CourseMembership.Role.STUDENT
            ).exists()
        )
        can_manage = bool(teacher_allowed and can_author_course(actor, cohort))
        if not (can_learn or can_manage):
            return {}
        return {
            "kind": "class",
            "id": cohort.id,
            "title": cohort.title,
            "teaching_url": reverse("liveclassroom:teacher-class-detail", args=[cohort.id]) if can_manage else "",
            "learning_url": reverse("liveclassroom:learn-class-detail", args=[cohort.id]) if can_learn else "",
            "results_url": (
                reverse("liveclassroom:teacher-class-results", args=[cohort.id])
                if can_manage
                and host_can_view_grade_summary(
                    actor=actor,
                    course_id=cohort.id,
                    package_allowed=can_manage,
                )
                else ""
            ),
        }

    @staticmethod
    def _course_navigation_context(teaching_course, actor, authenticated, teacher_allowed) -> dict[str, object]:
        if teaching_course is None:
            return {}
        cohorts = Course.objects.filter(teaching_course=teaching_course)
        can_learn = bool(
            authenticated
            and cohorts.filter(memberships__user=actor, memberships__role=CourseMembership.Role.STUDENT).exists()
        )
        can_manage = bool(
            teacher_allowed
            and (
                actor.is_superuser
                or teaching_course.created_by_id == actor.pk
                or any(can_author_course(actor, cohort) for cohort in cohorts)
            )
        )
        if not (can_learn or can_manage):
            return {}
        return {
            "kind": "course",
            "id": teaching_course.id,
            "title": teaching_course.title,
            "teaching_url": (
                reverse("liveclassroom:teacher-course-detail", args=[teaching_course.id]) if can_manage else ""
            ),
            "learning_url": (
                reverse("liveclassroom:learn-course-detail", args=[teaching_course.id]) if can_learn else ""
            ),
        }

    def _object_context_course(self, actor):
        """Return an object's related cohort; callers still apply visibility rules."""
        kwargs = self.kwargs
        course_id = None
        if kwargs.get("session_id") is not None:
            course_id = LiveSession.objects.filter(pk=kwargs["session_id"]).values_list("course_id", flat=True).first()
        elif kwargs.get("flow_id") is not None:
            course_id = Flow.objects.filter(pk=kwargs["flow_id"]).values_list("course_id", flat=True).first()
        elif kwargs.get("deck_id") is not None:
            course_id = Deck.objects.filter(pk=kwargs["deck_id"], owner=actor).values_list(
                "course_id", flat=True
            ).first()
        elif kwargs.get("assessment_id") is not None:
            course_id = AssessmentDefinition.objects.filter(
                pk=kwargs["assessment_id"], owner=actor
            ).values_list("course_id", flat=True).first()
        elif kwargs.get("attempt_id") is not None:
            course_id = AssessmentAttempt.objects.filter(
                public_id=kwargs["attempt_id"], user=actor
            ).values_list("run__course_id", flat=True).first()
        return Course.objects.filter(pk=course_id).first() if course_id is not None else None

    @staticmethod
    def _navigation_reference(view_name, resolver) -> str:
        """Return an opaque, non-secret reference suitable for shell preferences."""
        kwargs = getattr(resolver, "kwargs", {}) or {}
        static = {
            "liveclassroom:home": "page:home",
            "liveclassroom:help": "page:help",
            "liveclassroom:join": "page:join",
            "liveclassroom:teacher-dashboard": "page:teacher",
            "liveclassroom:teacher-courses": "page:teaching-courses",
            "liveclassroom:teacher-classes": "page:teaching-classes",
            "liveclassroom:teacher-sessions": "page:teacher-sessions",
            "liveclassroom:teacher-results": "page:teacher-results",
            "liveclassroom:teacher-library-lessons": "page:lessons",
            "liveclassroom:teacher-library-decks": "page:decks",
            "liveclassroom:teacher-library-assessments": "page:assessments",
            "liveclassroom:teacher-library-questions": "page:questions",
            "liveclassroom:teacher-library-shared": "page:shared",
            "liveclassroom:learning-home": "page:learning",
            "liveclassroom:assessment-history": "page:history",
            "liveclassroom:student-preview": "page:student-preview",
        }
        if view_name in static:
            return static[view_name]
        if view_name in {"liveclassroom:teacher-class-detail", "liveclassroom:teacher-class-results"}:
            return f"class:{kwargs.get('class_id')}:teaching"
        if view_name == "liveclassroom:learn-class-detail":
            return f"class:{kwargs.get('class_id')}:learning"
        if view_name == "liveclassroom:teacher-course-detail":
            return f"course:{kwargs.get('course_id')}:teaching"
        if view_name == "liveclassroom:learn-course-detail":
            return f"course:{kwargs.get('course_id')}:learning"
        if view_name == "liveclassroom:teacher-console":
            return f"session:{kwargs.get('session_id')}:teaching"
        if view_name == "liveclassroom:student-session":
            return f"session:{kwargs.get('session_id')}:learning"
        if view_name == "liveclassroom:student-view":
            return f"session:{kwargs.get('session_id')}:preview"
        if view_name == "liveclassroom:flow-builder-detail":
            return f"flow:{kwargs.get('flow_id')}"
        if view_name == "liveclassroom:deck-workspace-detail":
            return f"deck:{kwargs.get('deck_id')}"
        if view_name == "liveclassroom:assessment-workspace-detail":
            return f"assessment:{kwargs.get('assessment_id')}"
        if view_name in {"liveclassroom:learn-attempt-detail", "liveclassroom:learn-attempt-review"}:
            return f"attempt:{kwargs.get('attempt_id')}"
        return ""


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


class TeacherSessionListView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Render a bounded, authorized teacher session index."""

    template_name = "liveclassroom/teacher_sessions.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actor = self.request.user
        staff_courses = Course.objects.filter(
            Q(created_by=actor)
            | Q(
                memberships__user=actor,
                memberships__role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
            )
        ).distinct()
        context["sessions"] = (
            LiveSession.objects.filter(Q(teacher=actor) | Q(course__in=staff_courses))
            .select_related("course")
            .distinct()
            .order_by("-updated_at", "-id")[:100]
        )
        return context


class StudentPreviewChooserView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """List staff-authorized sessions before an explicit test-student action."""

    template_name = "liveclassroom/student_preview_chooser.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actor = self.request.user
        staff_courses = Course.objects.filter(
            Q(created_by=actor)
            | Q(
                memberships__user=actor,
                memberships__role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT],
            )
        ).distinct()
        context["sessions"] = (
            LiveSession.objects.filter(Q(teacher=actor) | Q(course__in=staff_courses))
            .exclude(status=LiveSession.Status.ENDED)
            .select_related("course")
            .distinct()
            .order_by("-updated_at", "-id")[:100]
        )
        return context


class ResultsWorkspaceView(TeacherRequiredMixin, LocaleContextMixin, TemplateView):
    """Global teacher results and grading destination.

    Class-specific result summaries remain addressable through
    :class:`ClassResultsView`; this page is the stable entry point for finding
    those summaries and working through the authorized grading queue.
    """

    template_name = "liveclassroom/results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["api_root"] = reverse("liveclassroom:api-v1-workspace")
        context["navigation_url"] = reverse("liveclassroom:api-v1-browse-navigation")
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
        package_allowed = can_author_course(self.request.user, course)
        if not package_allowed or not host_can_view_grade_summary(
            actor=self.request.user,
            course_id=course.id,
            package_allowed=package_allowed,
        ):
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
        context["classroom_shell"] = False
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
