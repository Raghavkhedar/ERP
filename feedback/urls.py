from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("", views.feedback_list, name="list"),
    path("new/", views.new_feedback, name="new"),
    path("<int:pk>/", views.feedback_detail, name="detail"),
    path("<int:pk>/comment/", views.new_comment, name="comment"),
    path("files/<int:pk>/", views.attachment, name="attachment"),
]
