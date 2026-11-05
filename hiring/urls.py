from django.urls import path

from . import source_views, views

app_name = "hiring"

urlpatterns = [
    path("requisitions/", views.requisition_list, name="list"),
    path("requisitions/export/", views.export_requisitions, name="export"),
    path("requisitions/new/", views.new_requisition, name="new"),
    path("requisitions/<int:pk>/edit/", views.edit_requisition, name="edit"),
    path("requisitions/<int:pk>/close/", views.close_requisition, name="close"),
    path("sourcing/", source_views.sourcing, name="sourcing"),
    path("sourcing/export/", source_views.export_sourced, name="sourcing_export"),
    path("sourcing/new/", source_views.new_source, name="source_new"),
    path("sourcing/import/", source_views.import_source, name="source_import"),
]
