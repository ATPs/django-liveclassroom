from django import forms
from django.db.models import Q

from .conf import default_session_mode, guests_allowed, join_code_length
from .models import CourseMembership, Flow, LiveSession


class CreateSessionForm(forms.ModelForm):
    class Meta:
        model = LiveSession
        fields = ["title", "course", "flow", "mode", "access_mode", "admission_mode", "chat_enabled"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["mode"].initial = default_session_mode()
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
            Q(course__in=self.fields["course"].queryset) | Q(created_by=user)
        ).distinct()

    def clean(self):
        cleaned_data = super().clean()
        course = cleaned_data.get("course")
        flow = cleaned_data.get("flow")
        if course and flow and flow.course_id != course.id:
            self.add_error("flow", "Choose a flow belonging to the selected course.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.teacher = self.user
        if instance.course_id is None and instance.flow_id and instance.flow.course_id:
            instance.course = instance.flow.course
        if commit:
            instance.save()
        return instance


class JoinSessionForm(forms.Form):
    join_code = forms.CharField(label="Join code")
    display_name = forms.CharField(max_length=100, label="Your name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["join_code"].max_length = join_code_length()
