from django.urls import path

from . import api, views

app_name = "liveclassroom"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("teacher/", views.TeacherDashboardView.as_view(), name="teacher-dashboard"),
    path("teacher/sessions/<int:session_id>/", views.TeacherConsoleView.as_view(), name="teacher-console"),
    path("join/", views.JoinView.as_view(), name="join"),
    path("sessions/<int:session_id>/", views.StudentSessionView.as_view(), name="student-session"),
    path("health/", views.health, name="health"),
    path("api/sessions/<int:session_id>/start/", api.start, name="api-start"),
    path("api/sessions/<int:session_id>/activities/", api.launch, name="api-launch"),
    path("api/activities/<int:activity_id>/close/", api.transition, {"state": "closed"}, name="api-close"),
    path("api/activities/<int:activity_id>/reveal/", api.transition, {"state": "revealed"}, name="api-reveal"),
    path("api/sessions/join/<str:join_code>/", api.join, name="api-join"),
    path("api/sessions/<int:session_id>/state/", api.state, name="api-state"),
    path("api/activities/<int:activity_id>/submissions/", api.submit, name="api-submit"),
    path("api/activities/<int:activity_id>/results/", api.results, name="api-results"),
]
