from django.urls import path

from . import offer_views, screening_views, selecting_views, source_views, views

app_name = "hiring"

urlpatterns = [
    path("requisitions/", views.requisition_list, name="list"),
    path("requisitions/export/", views.export_requisitions, name="export"),
    path("requisitions/new/", views.new_requisition, name="new"),
    path("requisitions/<int:pk>/", views.requisition_detail, name="detail"),
    path("requisitions/<int:pk>/post/", views.post_to_requisition, name="post"),
    path(
        "requisitions/<int:pk>/post/<int:post_pk>/edit/",
        views.edit_job_post,
        name="edit_post",
    ),
    path("requisitions/<int:pk>/edit/", views.edit_requisition, name="edit"),
    path("requisitions/<int:pk>/close/", views.close_requisition, name="close"),
    path("requisitions/<int:pk>/reopen/", views.reopen_requisition, name="reopen"),
    path("report/", views.report, name="report"),
    path("report/export/", views.export_report, name="report_export"),
    path("sourcing/", source_views.sourcing, name="sourcing"),
    path("sourcing/export/", source_views.export_sourced, name="sourcing_export"),
    path("sourcing/new/", source_views.new_source, name="source_new"),
    path("sourcing/import/", source_views.import_source, name="source_import"),
    path("screening/", screening_views.screening, name="screening"),
    path("calling/", screening_views.calling, name="calling"),
    path("calling/new/", screening_views.call_new, name="call_new"),
    path("calling/people/", screening_views.calling_people, name="calling_people"),
    path("calling/export/", screening_views.export_calling, name="calling_export"),
    path(
        "screening/<int:pk>/snooze/",
        screening_views.snooze_followup,
        name="followup_snooze",
    ),
    path("screening/bulk/", screening_views.bulk, name="bulk"),
    path("screening/shift/", screening_views.shift, name="shift"),
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
    path(
        "screening/person/<int:pk>/call/",
        screening_views.schedule_for_person,
        name="schedule_call",
    ),
    path("selecting/", selecting_views.selecting, name="selecting"),
    path(
        "selecting/export/", selecting_views.export_interviews, name="selecting_export"
    ),
    path("selecting/<int:pk>/interview/", selecting_views.record, name="interview"),
    path(
        "hiring/interviews/<int:pk>/<str:name>/",
        selecting_views.interview_file,
        name="interview_file",
    ),
    path(
        "hiring/interviews/<int:pk>/",
        selecting_views.review,
        name="interview_review",
    ),
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
    path("onboarding/", offer_views.onboarding_page, name="onboarding"),
    path("onboarding/export/", offer_views.export_onboarding, name="onboarding_export"),
    path("onboarding/<int:pk>/joined/", offer_views.joined, name="joined"),
    path("onboarding/<int:pk>/not-joined/", offer_views.not_joined, name="not_joined"),
]
