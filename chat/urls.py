from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/messages/", views.send_message, name="send_message"),
]
