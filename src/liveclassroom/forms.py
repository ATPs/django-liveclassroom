from django import forms

from .models import CourseMembership, Flow, LiveSession


class CreateSessionForm(forms.ModelForm):
    class Meta:
        model = LiveSession
        fields = ["course", "flow", "mode"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        courses = CourseMembership.objects.filter(
            user=user, role__in=[CourseMembership.Role.TEACHER, CourseMembership.Role.ASSISTANT]
        ).values_list("course_id", flat=True)
        self.fields["course"].queryset = self.fields["course"].queryset.filter(id__in=courses) | self.fields[
            "course"
        ].queryset.filter(created_by=user)
        self.fields["flow"].queryset = Flow.objects.filter(course__in=self.fields["course"].queryset)

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
        if commit:
            instance.save()
        return instance


class JoinSessionForm(forms.Form):
    join_code = forms.CharField(max_length=12, label="Join code")
    display_name = forms.CharField(max_length=100, label="Your name")
