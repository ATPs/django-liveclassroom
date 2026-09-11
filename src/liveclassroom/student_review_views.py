"""Authenticated student history/review page bootstrap."""

from uuid import UUID

from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.generic import TemplateView

from .views import LocaleContextMixin

_URL_MARKER = "__id__"
_PLACEHOLDER_ID = UUID(int=0)


def _url_template(name: str) -> str:
    """Reverse a UUID route once and leave a mount-safe replacement marker."""
    return reverse(name, args=[_PLACEHOLDER_ID]).replace(str(_PLACEHOLDER_ID), _URL_MARKER)


class StudentReviewView(LoginRequiredMixin, LocaleContextMixin, TemplateView):
    """Render the read-only student history/review surface.

    The page has no attempt side effects.  It receives only endpoint templates;
    the browser starts/resumes an attempt after the learner explicitly chooses
    that action.
    """

    template_name = "liveclassroom/student_review.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "history_url": reverse("liveclassroom:api-v1-assessment-history"),
                "review_url_template": _url_template("liveclassroom:api-v1-attempt-review"),
                "start_url_template": _url_template("liveclassroom:api-v1-assessment-attempts"),
                "available_url_template": _url_template("liveclassroom:api-v1-available-assessment-run"),
                "assessment_url_template": _url_template("liveclassroom:assessment-attempt"),
                "export_url_template": _url_template("liveclassroom:api-v1-attempt-result-export"),
            }
        )
        return context


__all__ = ["StudentReviewView"]
