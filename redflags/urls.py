from django.urls import path

from . import views

app_name = "redflags"

urlpatterns = [
    path("", views.red_flag_list, name="list"),
    path("export/", views.export_red_flags, name="export"),
    path("new/", views.new_red_flag, name="new"),
    path("sent/", views.sent, name="sent"),
    path("<int:pk>/", views.red_flag_detail, name="detail"),
    path("<int:pk>/note/", views.new_note, name="note"),
    path("<int:pk>/status/", views.change_status, name="status"),
    path("<int:pk>/assign/", views.assign, name="assign"),
    path("<int:pk>/unassign/", views.remove_assignment, name="unassign"),
    path("files/<int:pk>/", views.attachment, name="attachment"),
]
