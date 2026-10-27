from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import DailyPlan, PlanItem


class PlanItemInline(admin.TabularInline):
    model = PlanItem
    extra = 0


@admin.register(DailyPlan)
class DailyPlanAdmin(SimpleHistoryAdmin):
    list_display = ["user", "date", "updated_at"]
    list_filter = ["date"]
    search_fields = ["user__username", "user__first_name"]
    date_hierarchy = "date"
    raw_id_fields = ["user"]
    inlines = [PlanItemInline]
