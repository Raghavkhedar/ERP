from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import PRIORITIES, Status, Task


class PersonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.display_name


class TaskForm(forms.ModelForm):
    assigned_to = PersonChoiceField(
        queryset=get_user_model().objects.none(),
        label="Assign to",
        empty_label="Choose a person",
        error_messages={"required": "Choose who does the task."},
    )
    priority = forms.TypedChoiceField(
        choices=[("", "Choose")] + [(p, p) for p in PRIORITIES],
        coerce=int,
        help_text="1 is the most urgent.",
        error_messages={"required": "Choose a priority."},
    )

    class Meta:
        model = Task
        fields = ["assigned_to", "priority", "description", "due_date"]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "placeholder": "What is the report or job?"}
            ),
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        error_messages = {
            "description": {"required": "Describe the report or job."},
            "due_date": {"required": "Pick a completion date."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = (
            get_user_model()
            .objects.filter(is_active=True)
            .order_by("first_name", "last_name", "username")
        )
        self.fields["due_date"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean_description(self):
        description = self.cleaned_data["description"].strip()
        if not description:
            raise forms.ValidationError("Describe the report or job.")
        return description

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        received = (
            timezone.localdate(self.instance.received_at)
            if self.instance.pk
            else timezone.localdate()
        )
        if due_date < received:
            raise forms.ValidationError(
                "The completion date can't be before the task was received."
            )
        return due_date


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Status.choices)
