from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from .export import chats_workbook
from .forms import ChannelForm, MessageForm
from .models import Conversation, ConversationKind
from .services import (
    add_member,
    can_add_people,
    conversation_title,
    create_channel,
    get_or_create_dm,
    is_member,
    join,
    mark_read,
    newest_incoming,
    unread_counts,
    visible_conversations,
)

MESSAGE_LIMIT = 200


def _sidebar(user, current_id=None):
    conversations = list(
        visible_conversations(user).prefetch_related("memberships__user")
    )
    unread = unread_counts(user)
    for conversation in conversations:
        conversation.title = conversation_title(conversation, user)
        conversation.unread = unread.get(conversation.pk, 0)
    conversations.sort(key=lambda c: c.title.lower())
    return {
        "channels": [c for c in conversations if c.kind == ConversationKind.CHANNEL],
        "direct_messages": [
            c for c in conversations if c.kind == ConversationKind.DIRECT
        ],
        "current_id": current_id,
    }


def _latest_messages(conversation):
    latest = conversation.messages.select_related("author").order_by("-id")
    return reversed(latest[:MESSAGE_LIMIT])


@login_required
def conversation_list(request):
    return render(request, "chat/conversation_list.html", _sidebar(request.user))


@login_required
@require_GET
def export_chats(request):
    """Every conversation you are in, with all its messages."""
    mine = Conversation.objects.filter(memberships__user=request.user)
    return chats_workbook(mine.select_related("created_by"), request.user, "chats")


@login_required
@require_GET
def export_conversation(request, pk):
    """One conversation with all its messages, not only the latest page. Like
    reading it, only members may export it.
    """
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    if not is_member(conversation, request.user):
        return HttpResponseForbidden("Join this conversation to export its messages.")
    one = Conversation.objects.filter(pk=conversation.pk).select_related("created_by")
    title = conversation_title(conversation, request.user)
    slug = "".join(ch if ch.isalnum() else "-" for ch in title).strip("-").lower()
    return chats_workbook(one, request.user, f"chat-{slug or conversation.pk}")


@login_required
@require_GET
def pulse(request):
    """Unread total and newest incoming message id, for the chat button."""
    return JsonResponse(
        {
            "unread": sum(unread_counts(request.user).values()),
            "newest": newest_incoming(request.user),
        }
    )


@login_required
@require_GET
def sidebar(request):
    current = request.GET.get("current", "")
    current_id = int(current) if current.isdigit() else None
    return render(
        request, "chat/_sidebar_items.html", _sidebar(request.user, current_id)
    )


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    member = is_member(conversation, request.user)
    mark_read(conversation, request.user)
    context = _sidebar(request.user, current_id=conversation.pk) | {
        "conversation": conversation,
        "title": conversation_title(conversation, request.user),
        "is_member": member,
        "can_add_people": can_add_people(conversation, request.user),
        "chat_messages": _latest_messages(conversation) if member else [],
    }
    return render(request, "chat/conversation_detail.html", context)


@login_required
@require_GET
def latest_messages(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    if not is_member(conversation, request.user):
        return HttpResponseForbidden("Join this conversation to see its messages.")
    mark_read(conversation, request.user)
    return render(
        request,
        "chat/_message_list.html",
        {"chat_messages": _latest_messages(conversation)},
    )


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


@login_required
@require_POST
def join_conversation(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    join(conversation, request.user)
    return redirect("chat:conversation_detail", pk=conversation.pk)


@login_required
def new_dm(request):
    people = (
        get_user_model()
        .objects.filter(is_active=True)
        .exclude(pk=request.user.pk)
        .order_by("first_name", "last_name", "username")
    )
    context = _sidebar(request.user) | {"people": people}
    return render(request, "chat/new_dm.html", context)


@login_required
@require_POST
def open_dm(request, user_id):
    other = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    dm = get_or_create_dm(request.user, other)
    return redirect("chat:conversation_detail", pk=dm.pk)


@login_required
def new_channel(request):
    form = ChannelForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        channel = create_channel(
            request.user, form.cleaned_data["name"], form.cleaned_data["is_private"]
        )
        return redirect("chat:conversation_detail", pk=channel.pk)
    context = _sidebar(request.user) | {"form": form}
    return render(request, "chat/new_channel.html", context)


@login_required
def add_people(request, pk):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    if not can_add_people(conversation, request.user):
        return HttpResponseForbidden("Only the creator and Office admins add people.")
    people = (
        get_user_model()
        .objects.filter(is_active=True)
        .exclude(chat_memberships__conversation=conversation)
        .order_by("first_name", "last_name", "username")
    )
    context = _sidebar(request.user, current_id=conversation.pk) | {
        "conversation": conversation,
        "title": conversation_title(conversation, request.user),
        "people": people,
    }
    return render(request, "chat/add_people.html", context)


@login_required
@require_POST
def add_person(request, pk, user_id):
    conversation = get_object_or_404(visible_conversations(request.user), pk=pk)
    if not can_add_people(conversation, request.user):
        return HttpResponseForbidden("Only the creator and Office admins add people.")
    person = get_object_or_404(get_user_model(), pk=user_id, is_active=True)
    add_member(conversation, request.user, person)
    return redirect("chat:add_people", pk=conversation.pk)
