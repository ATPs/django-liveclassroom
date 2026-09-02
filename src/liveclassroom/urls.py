from django.urls import path

from . import views

app_name = "liveclassroom"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("teacher/", views.TeacherConsoleView.as_view(), name="teacher-console"),
    path("join/", views.JoinView.as_view(), name="join"),
    path("health/", views.health, name="health"),
]
