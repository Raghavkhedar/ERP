from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import ConversationKind
from .services import conversation_title, visible_conversations

MESSAGE_LIMIT = 200


def _sidebar(user):
    conversations = list(
        visible_conversations(user).prefetch_related("memberships__user")
    )
    for conversation in conversations:
        conversation.title = conversation_title(conversation, user)
    conversations.sort(key=lambda c: c.title.lower())
    return {
        "channels": [c for c in conversations if c.kind == ConversationKind.CHANNEL],
        "direct_messages": [
            c for c in conversations if c.kind == ConversationKind.DIRECT
        ],
    }


@login_required
def conversation_list(request):
    return render(request, "chat/conversation_list.html", _sidebar(request.user))


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    latest = conversation.messages.select_related("author").order_by("-id")
    context = _sidebar(request.user) | {
        "conversation": conversation,
        "title": conversation_title(conversation, request.user),
        "chat_messages": reversed(latest[:MESSAGE_LIMIT]),
    }
    return render(request, "chat/conversation_detail.html", context)
