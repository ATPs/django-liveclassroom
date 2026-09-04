from django.urls import include, path

urlpatterns = [path("classroom/", include("liveclassroom.urls"))]
