from django import forms
from django.db.models import Q

from tasks.forms import FilesMixin

from .models import Area, Feedback, Kind, Lesson, Outcome, Status


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


class ResolutionForm(forms.Form):
    status = forms.ChoiceField(choices=Status.choices)
    outcome = forms.ChoiceField(
        choices=[("", "Not decided")] + Outcome.choices, required=False
    )

    def clean(self):
        data = super().clean()
        if data.get("status") == Status.RESOLVED and not data.get("outcome"):
            self.add_error("outcome", "Choose what came of it to resolve it.")
        return data


class FeedbackChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, feedback):
        return f"{feedback.summary} ({feedback.submitter.display_name})"


class LessonForm(forms.ModelForm):
    feedback = FeedbackChoiceField(
        queryset=Feedback.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Written from this feedback",
        help_text="Feedback marked as becoming a lesson, plus what you pick here.",
    )

    class Meta:
        model = Lesson
        fields = [
            "title",
            "area",
            "what_happened",
            "why_it_happens",
            "what_to_teach",
            "feedback",
        ]
        labels = {
            "area": "Module",
            "what_happened": "What went wrong",
            "why_it_happens": "Why it happens",
            "what_to_teach": "What to teach",
        }
        help_texts = {
            "what_to_teach": "What a trainer should cover early, to prevent it.",
        }
        widgets = {
            "what_happened": forms.Textarea(attrs={"rows": 4}),
            "why_it_happens": forms.Textarea(attrs={"rows": 3}),
            "what_to_teach": forms.Textarea(attrs={"rows": 5}),
        }
        error_messages = {
            "title": {"required": "Give the lesson a title."},
            "area": {"required": "Choose the module."},
            "what_happened": {"required": "Describe what went wrong."},
            "what_to_teach": {"required": "Say what to teach."},
        }

    def __init__(self, *args, linked=(), **kwargs):
        super().__init__(*args, **kwargs)
        chosen = set(linked)
        if self.instance.pk:
            chosen.update(self.instance.feedback.values_list("pk", flat=True))
        self.fields["feedback"].queryset = Feedback.objects.filter(
            Q(outcome=Outcome.LESSON) | Q(pk__in=chosen)
        ).select_related("submitter")
        self.fields["area"].choices = [("", "Choose")] + Area.choices
