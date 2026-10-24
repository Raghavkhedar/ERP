from django.urls import path

from . import views

app_name = "plans"

urlpatterns = [
    path("today/", views.today, name="today"),
]
