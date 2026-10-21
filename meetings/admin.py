from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Invitation, Meeting


class InvitationInline(admin.TabularInline):
    model = Invitation
    extra = 0
    raw_id_fields = ["invitee"]


@admin.register(Meeting)
class MeetingAdmin(SimpleHistoryAdmin):
    list_display = ["title", "organizer", "starts_at", "ends_at", "cancelled_at"]
    list_filter = ["starts_at"]
    search_fields = ["title"]
    date_hierarchy = "starts_at"
    raw_id_fields = ["organizer"]
    inlines = [InvitationInline]
