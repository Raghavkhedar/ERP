from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Attachment, Comment, Feedback, Lesson


@admin.register(Feedback)
class FeedbackAdmin(SimpleHistoryAdmin):
    list_display = ["__str__", "kind", "area", "status", "created_at"]
    list_filter = ["kind", "area", "status", "created_at"]
    search_fields = ["message", "submitter__username", "submitter__first_name"]
    date_hierarchy = "created_at"
    raw_id_fields = ["submitter"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["feedback", "author", "created_at", "body"]
    raw_id_fields = ["feedback", "author"]


@admin.register(Attachment)
class FeedbackAttachmentAdmin(admin.ModelAdmin):
    list_display = ["original_name", "feedback", "comment", "size"]
    raw_id_fields = ["feedback", "comment"]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    search_fields = ["what_happened", "what_to_teach"]
    raw_id_fields = ["created_by"]
    filter_horizontal = ["feedback"]
