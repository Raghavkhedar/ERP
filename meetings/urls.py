from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("", views.schedule, name="schedule"),
    path("open/", views.open_slots_view, name="open_slots"),
]
