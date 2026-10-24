from django import forms

from tasks.forms import FilesMixin

from .models import Area, Feedback, Kind


class FeedbackForm(FilesMixin, forms.ModelForm):
    kind = forms.ChoiceField(
        choices=[("", "Choose")] + Kind.choices,
        label="What is it?",
        error_messages={"required": "Choose what kind of feedback this is."},
    )
    area = forms.ChoiceField(
        choices=[("", "Choose")] + Area.choices,
        label="What is it about?",
        error_messages={"required": "Choose what it is about."},
    )

    class Meta:
        model = Feedback
        fields = ["kind", "area", "message"]
        labels = {"message": "Tell us"}
        widgets = {
            "message": forms.Textarea(
                attrs={"rows": 5, "placeholder": "What happened, or what would help?"}
            ),
        }
        error_messages = {"message": {"required": "Write your feedback."}}

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if not message:
            raise forms.ValidationError("Write your feedback.")
        return message


class CommentForm(FilesMixin, forms.Form):
    body = forms.CharField(
        label="Add to the discussion",
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"required": "Write a message."},
    )

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Write a message.")
        return body
