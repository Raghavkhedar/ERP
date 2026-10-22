from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("", views.schedule, name="schedule"),
    path("<int:year>/<int:month>/", views.schedule, name="month"),
    path("<int:year>/<int:month>/<int:day>/", views.day_view, name="day"),
    path("open/", views.open_slots_view, name="open_slots"),
    path("people/", views.people, name="people"),
    path("people/<int:user_id>/", views.person_slots, name="person_slots"),
    path("slots/<int:pk>/book/", views.book_slot, name="book"),
    path("slots/<int:pk>/cancel/", views.cancel_slot, name="cancel"),
]
