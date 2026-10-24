from django.utils import timezone
from django.utils.text import Truncator

from .models import Notification

RECENT_LIMIT = 20
PULSE_LIMIT = 10


def notify(user, text, url=""):
    """Tell the user something. Inactive accounts are skipped."""
    if not user.is_active:
        return None
    return Notification.objects.create(
        user=user, text=Truncator(text).chars(300), url=url
    )


def unread_count(user):
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def recent(user, limit=RECENT_LIMIT):
    return list(Notification.objects.filter(user=user)[:limit])


def since(user, after_id, limit=PULSE_LIMIT):
    """Notifications newer than `after_id`, oldest first, up to `limit`."""
    pending = Notification.objects.filter(user=user, id__gt=after_id).order_by("id")
    return list(pending[:limit])


def latest_id(user):
    newest = Notification.objects.filter(user=user).first()
    return newest.id if newest else 0


def mark_read(user, pk):
    """Mark one of the user's notifications read and return it, or None."""
    notification = Notification.objects.filter(user=user, pk=pk).first()
    if notification and notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
    return notification


def mark_all_read(user):
    Notification.objects.filter(user=user, read_at__isnull=True).update(
        read_at=timezone.now()
    )
