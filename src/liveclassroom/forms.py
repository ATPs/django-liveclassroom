from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .conf import guests_allowed, join_code_length
from .models import CourseMembership, Flow, LiveSession
from .services.permissions import can_teach


class CreateSessionForm(forms.ModelForm):
    class Meta:
        model = LiveSession
        fields = ["title", "course", "flow", "access_mode", "admission_mode", "chat_enabled"]
        labels = {
            "title": _("Title"),
            "course": _("Course"),
            "flow": _("Flow"),
            "access_mode": _("Access mode"),
            "admission_mode": _("Admission mode"),
            "chat_enabled": _("Enable class chat"),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["access_mode"].choices = [
            (value, _(label)) for value, label in self.fields["access_mode"].choices
        ]
        self.fields["admission_mode"].choices = [
            (value, _(label)) for value, label in self.fields["admission_mode"].choices
        ]
        if not guests_allowed():
            self.fields["access_mode"].choices = [
                choice
                for choice in self.fields["access_mode"].choices
                if choice[0] == LiveSession.AccessMode.AUTHENTICATED
            ]
        courses = CourseMembership.objects.filter(
            user=user, role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT]
        ).values_list("course_id", flat=True)
        self.fields["course"].queryset = self.fields["course"].queryset.filter(id__in=courses) | self.fields[
            "course"
        ].queryset.filter(created_by=user)
        self.fields["flow"].queryset = Flow.objects.filter(
            Q(course__in=self.fields["course"].queryset)
            | Q(created_by=user)
            | Q(shares__user=user)
            | (Q(demo_lesson__is_public=True) if can_teach(user) else Q(pk__in=[]))
        ).distinct()

    def save(self, commit=True):
        from .services.plans import create_session
        if not commit:
            instance = super().save(commit=False)
            instance.teacher = self.user
            return instance
        return create_session(owner=self.user, **self.cleaned_data)


class JoinSessionForm(forms.Form):
    join_code = forms.CharField(label=_("Join code"))
    display_name = forms.CharField(max_length=100, label=_("Your name"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["join_code"].max_length = join_code_length()
