from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import MessageForm
from .models import ConversationKind
from .services import conversation_title, is_member, visible_conversations

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
        "can_send": is_member(conversation, request.user),
    }
    return render(request, "chat/conversation_detail.html", context)


@login_required
@require_POST
def send_message(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    if not is_member(conversation, request.user):
        return HttpResponseForbidden("Join this conversation to send messages.")
    form = MessageForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("A message needs text, up to 4000 characters.")
    message = form.save(commit=False)
    message.conversation = conversation
    message.author = request.user
    message.save()
    if request.headers.get("HX-Request"):
        return render(request, "chat/_message.html", {"message": message})
    return redirect("chat:conversation_detail", pk=conversation.pk)
