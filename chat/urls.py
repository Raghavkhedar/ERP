from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("sidebar/", views.sidebar, name="sidebar"),
    path("dm/new/", views.new_dm, name="new_dm"),
    path("dm/<int:user_id>/", views.open_dm, name="open_dm"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/join/", views.join_conversation, name="join"),
    path("<int:pk>/messages/", views.send_message, name="send_message"),
    path("<int:pk>/messages/latest/", views.latest_messages, name="latest_messages"),
]
