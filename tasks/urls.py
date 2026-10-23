from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="list"),
    path("new/", views.new_task, name="new"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.edit_task, name="edit"),
    path("<int:pk>/status/", views.change_status, name="status"),
]
