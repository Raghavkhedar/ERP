from core.export import stamp, workbook_response

from .models import Message
from .services import conversation_title


def chats_workbook(conversations, viewer, name):
    """Every message of `conversations`, oldest first, for someone who is a
    member of each. Titles are the ones the viewer sees (a DM is the other
    person), and system lines read as 'added <person>'.
    """
    conversations = list(conversations.prefetch_related("memberships__user"))
    titles = {c.pk: conversation_title(c, viewer) for c in conversations}
    info = [
        (
            titles[c.pk],
            c.get_kind_display(),
            "Private" if c.is_private else "Public" if c.kind == "channel" else "",
            ", ".join(m.user.display_name for m in c.memberships.all()),
            c.created_by.display_name,
            c.created_at,
        )
        for c in conversations
    ]
    messages = (
        Message.objects.filter(conversation__in=conversations)
        .select_related("author", "subject")
        .order_by("conversation_id", "id")
    )
    rows = [
        (
            titles[m.conversation_id],
            m.created_at,
            m.author.display_name,
            m.get_kind_display(),
            m.body,
            m.subject.display_name if m.subject else "",
        )
        for m in messages
    ]
    return workbook_response(
        stamp(name),
        {
            "Conversations": (
                ("Conversation", "Type", "Access", "Members", "Created by", "Created"),
                info,
            ),
            "Messages": (
                ("Conversation", "Sent", "From", "Kind", "Message", "About"),
                rows,
            ),
        },
    )
