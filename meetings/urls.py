from django.urls import path

from . import conference_views as conferences
from . import views

app_name = "meetings"

urlpatterns = [
    path("", views.schedule, name="schedule"),
    path("<int:year>/<int:month>/", views.schedule, name="month"),
    path("<int:year>/<int:month>/<int:day>/", views.day_view, name="day"),
    path("export/", views.export_schedule, name="export"),
    path("block/", views.block_time, name="block_time"),
    path("block/<int:year>/<int:month>/<int:day>/", views.block_time, name="block_day"),
    path("people/", views.people, name="people"),
    path("people/<int:user_id>/", views.person_slots, name="person_slots"),
    path("slots/<int:pk>/book/", views.book_slot, name="book"),
    path("slots/<int:pk>/cancel/", views.cancel_slot, name="cancel"),
    path("conferences/", conferences.conferences, name="conferences"),
    path("conferences/new/", conferences.conference_new, name="conference_new"),
    path(
        "conferences/<int:pk>/", conferences.conference_detail, name="conference_detail"
    ),
    path(
        "conferences/<int:pk>/edit/",
        conferences.conference_edit,
        name="conference_edit",
    ),
    path(
        "conferences/<int:pk>/respond/",
        conferences.conference_respond,
        name="conference_respond",
    ),
    path(
        "conferences/<int:pk>/cancel/",
        conferences.conference_cancel,
        name="conference_cancel",
    ),
    path(
        "conferences/<int:pk>/invite/",
        conferences.conference_invite,
        name="conference_invite",
    ),
    path(
        "conferences/<int:pk>/remove/<int:user_id>/",
        conferences.conference_remove,
        name="conference_remove",
    ),
]
