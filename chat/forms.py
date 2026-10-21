from django import forms

from .models import Conversation, ConversationKind, Message


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["body"]


class ChannelForm(forms.ModelForm):
    class Meta:
        model = Conversation
        fields = ["name", "is_private"]
        labels = {"is_private": "Private: only people who are added can see it"}

    def clean_name(self):
        name = self.cleaned_data["name"].strip().lstrip("#").strip()
        if not name:
            raise forms.ValidationError("Give the channel a name.")
        taken = Conversation.objects.filter(
            kind=ConversationKind.CHANNEL, name__iexact=name
        )
        if taken.exists():
            raise forms.ValidationError("A channel with this name already exists.")
        return name
