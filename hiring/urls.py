from django.urls import path

from . import views

app_name = "hiring"

urlpatterns = [
    path("", views.requisition_list, name="list"),
    path("export/", views.export_requisitions, name="export"),
    path("new/", views.new_requisition, name="new"),
    path("<int:pk>/edit/", views.edit_requisition, name="edit"),
    path("<int:pk>/close/", views.close_requisition, name="close"),
]
