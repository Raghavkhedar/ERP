from django.urls import path

from . import views

app_name = "people"

urlpatterns = [
    path("", views.person_list, name="list"),
    path("export/", views.export_people, name="export"),
    path("new/", views.new_person, name="new"),
    path("<int:pk>/", views.person_detail, name="detail"),
    path("<int:pk>/edit/", views.edit_person, name="edit"),
    path("<int:pk>/archive/", views.archive_person, name="archive"),
]
