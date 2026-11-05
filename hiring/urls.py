from django.urls import path

from . import offer_views, screening_views, selecting_views, source_views, views

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
    path("screening/", screening_views.screening, name="screening"),
    path(
        "screening/export/", screening_views.export_followups, name="screening_export"
    ),
    path("screening/<int:pk>/", screening_views.followup_detail, name="followup"),
    path(
        "screening/<int:pk>/call/", screening_views.log_followup, name="followup_call"
    ),
    path(
        "screening/<int:pk>/reschedule/",
        screening_views.reschedule_followup,
        name="followup_reschedule",
    ),
    path(
        "screening/<int:pk>/reassign/",
        screening_views.reassign_followup,
        name="followup_reassign",
    ),
    path(
        "screening/<int:pk>/cancel/",
        screening_views.cancel_followup,
        name="followup_cancel",
    ),
    path("selecting/", selecting_views.selecting, name="selecting"),
    path(
        "selecting/export/", selecting_views.export_interviews, name="selecting_export"
    ),
    path("selecting/<int:pk>/interview/", selecting_views.record, name="interview"),
    path("selecting/<int:pk>/hr/", selecting_views.assess, name="assess"),
    path("hiring/", offer_views.hiring, name="offers"),
    path("hiring/export/", offer_views.export_offers, name="offers_export"),
    path("hiring/<int:pk>/start/", offer_views.begin, name="offer_start"),
    path("hiring/offer/<int:pk>/", offer_views.offer_detail, name="offer"),
    path("hiring/offer/<int:pk>/round/", offer_views.new_round, name="offer_round"),
    path(
        "hiring/offer/<int:pk>/accept/", offer_views.accept_offer, name="offer_accept"
    ),
    path(
        "hiring/offer/<int:pk>/decline/",
        offer_views.decline_offer,
        name="offer_decline",
    ),
]
