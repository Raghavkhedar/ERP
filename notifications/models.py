from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Something a person should know about, shown in their bell and as a popup."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    text = models.CharField(max_length=300)
    url = models.CharField(
        max_length=300, blank=True, help_text="Where clicking it goes, on this site."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["user", "id"], name="notifications_user_id_idx"),
        ]

    def __str__(self):
        return f"{self.user}: {self.text}"
