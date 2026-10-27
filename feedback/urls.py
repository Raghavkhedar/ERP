from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("", views.feedback_list, name="list"),
    path("new/", views.new_feedback, name="new"),
    path("<int:pk>/", views.feedback_detail, name="detail"),
    path("<int:pk>/comment/", views.new_comment, name="comment"),
    path("<int:pk>/resolve/", views.change_resolution, name="resolve"),
    path("<int:pk>/assign/", views.assign, name="assign"),
    path("<int:pk>/unassign/", views.remove_assignment, name="unassign"),
    path("lessons/", views.lesson_list, name="lessons"),
    path("lessons/new/", views.new_lesson, name="lesson_new"),
    path("lessons/<int:pk>/", views.lesson_detail, name="lesson"),
    path("lessons/<int:pk>/edit/", views.edit_lesson, name="lesson_edit"),
    path("files/<int:pk>/", views.attachment, name="attachment"),
]
