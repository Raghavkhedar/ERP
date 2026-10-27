from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.task_list, name="list"),
    path("timeline/", views.timeline, name="timeline"),
    path("new/", views.new_task, name="new"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.edit_task, name="edit"),
    path("<int:pk>/status/", views.change_status, name="status"),
    path("<int:pk>/nudge/", views.nudge_task, name="nudge"),
    path("alarms/", views.alarms, name="alarms"),
    path("<int:pk>/alarm/", views.task_alarm, name="alarm"),
    path("updates/new/", views.new_update, name="update_new"),
    path("files/<int:pk>/", views.attachment, name="attachment"),
]
