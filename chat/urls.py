from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.conversation_list, name="conversation_list"),
    path("pulse/", views.pulse, name="pulse"),
    path("sidebar/", views.sidebar, name="sidebar"),
    path("channels/new/", views.new_channel, name="new_channel"),
    path("dm/new/", views.new_dm, name="new_dm"),
    path("dm/<int:user_id>/", views.open_dm, name="open_dm"),
    path("<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("<int:pk>/join/", views.join_conversation, name="join"),
    path("<int:pk>/people/", views.add_people, name="add_people"),
    path("<int:pk>/people/<int:user_id>/add/", views.add_person, name="add_person"),
    path("<int:pk>/messages/", views.send_message, name="send_message"),
    path("<int:pk>/messages/latest/", views.latest_messages, name="latest_messages"),
]
