"""Template helpers for localized liveclassroom UI strings."""

from django import template
from django.utils.translation import gettext_lazy as _

register = template.Library()

_STATUS_LABELS = {
    "draft": _("Draft"),
    "live": _("Live"),
    "paused": _("Paused"),
    "ended": _("Ended"),
}


@register.filter
def status_label(value):
    """Localize a LiveSession status value, passing unknown values through."""
    return _STATUS_LABELS.get(value, value)
