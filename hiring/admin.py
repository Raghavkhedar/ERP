from django.contrib import admin

from core.admin_readonly import ReadOnly

from .models import CallLog, FollowUp, Interview, Offer, Requisition


class CallInline(ReadOnly, admin.TabularInline):
    model = CallLog
    fields = ["called_at", "caller", "outcome", "call_type", "notes"]
    readonly_fields = fields
    extra = 0
    show_change_link = True


class FollowUpInline(ReadOnly, admin.TabularInline):
    model = FollowUp
    fk_name = "person"
    fields = ["due", "purpose", "status", "owner", "requisition"]
    readonly_fields = fields
    extra = 0
    show_change_link = True


class InterviewInline(ReadOnly, admin.TabularInline):
    model = Interview
    fields = ["scheduled_at", "result", "requisition", "interviewer"]
    readonly_fields = fields
    extra = 0
    show_change_link = True


@admin.register(Requisition)
class RequisitionAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ["__str__", "company", "department", "status", "archived_at"]
    list_filter = ["company", "department", "status"]
    search_fields = ["profile"]


@admin.register(FollowUp)
class FollowUpAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ["person", "purpose", "due", "status", "owner"]
    list_filter = ["status", "purpose", "person__company"]
    search_fields = ["person__name", "person__phone", "person__phone_key"]
    raw_id_fields = ["person", "requisition", "owner"]


@admin.register(CallLog)
class CallLogAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ["person", "called_at", "caller", "outcome", "call_type"]
    list_filter = ["outcome", "call_type", "person__company"]
    search_fields = ["person__name", "person__phone", "person__phone_key"]
    raw_id_fields = ["person", "followup", "caller"]


@admin.register(Interview)
class InterviewAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ["person", "scheduled_at", "result", "interviewer"]
    list_filter = ["result", "person__company"]
    search_fields = ["person__name", "person__phone", "person__phone_key"]
    raw_id_fields = ["person", "requisition", "followup", "interviewer"]


@admin.register(Offer)
class OfferAdmin(ReadOnly, admin.ModelAdmin):
    list_display = ["person", "requisition", "state", "joining_date"]
    list_filter = ["state", "person__company"]
    search_fields = ["person__name", "person__phone", "person__phone_key"]
    raw_id_fields = ["person", "requisition", "made_by"]
