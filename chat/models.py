from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords


class ConversationKind(models.TextChoices):
    DIRECT = "direct", "Direct message"
    CHANNEL = "channel", "Channel"


class Conversation(models.Model):
    kind = models.CharField(max_length=10, choices=ConversationKind.choices)
    name = models.CharField(max_length=80, blank=True)
    is_private = models.BooleanField(default=False)
    dm_key = models.CharField(max_length=40, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=ConversationKind.values),
                name="chat_conversation_kind_valid",
            ),
            models.CheckConstraint(
                condition=(Q(kind=ConversationKind.CHANNEL, dm_key="") & ~Q(name=""))
                | (
                    Q(kind=ConversationKind.DIRECT, name="", is_private=False)
                    & ~Q(dm_key="")
                ),
                name="chat_conversation_shape",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=Q(kind=ConversationKind.CHANNEL),
                name="chat_unique_channel_name",
            ),
            models.UniqueConstraint(
                fields=["dm_key"],
                condition=Q(kind=ConversationKind.DIRECT),
                name="chat_unique_dm_pair",
            ),
        ]

    def __str__(self):
        if self.kind == ConversationKind.CHANNEL:
            return f"#{self.name}"
        return f"DM {self.dm_key}"


class Membership(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chat_memberships",
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_read_message = models.ForeignKey(
        "Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    history = HistoricalRecords(excluded_fields=["last_read_message"])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"], name="chat_unique_membership"
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.conversation}"


class MessageKind(models.TextChoices):
    USER = "user", "User message"
    SYSTEM = "system", "System message"
    NOTICE = "notice", "Notice"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.PROTECT, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chat_messages",
    )
    body = models.CharField(max_length=4000)
    # The person a system message is about ("added <subject>"). Stored as a
    # link, not as text, so leavers can be shown as "Former employee".
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(
        max_length=10, choices=MessageKind.choices, default=MessageKind.USER
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["conversation", "id"], name="chat_msg_conv_id_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(body__regex=r"\S"),
                name="chat_message_body_not_blank",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=MessageKind.values),
                name="chat_message_kind_valid",
            ),
        ]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"

    @property
    def is_system(self):
        return self.kind == MessageKind.SYSTEM

    @property
    def is_notice(self):
        return self.kind == MessageKind.NOTICE
