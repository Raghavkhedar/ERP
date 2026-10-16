from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Conversation, Membership, Message


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Conversation)
class ConversationAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "kind", "is_private", "created_by", "archived_at"]
    list_filter = ["kind", "is_private"]
    search_fields = ["name"]
    inlines = [MembershipInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["conversation", "author", "created_at", "body"]
    list_filter = ["conversation"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
