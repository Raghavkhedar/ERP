from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from django.template.defaultfilters import filesizeformat
from django.utils import timezone

from .models import PRIORITIES, Repeat, Status, Task


class PersonChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.display_name


MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_FILES = 10
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".pdf", ".txt", ".csv",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}  # fmt: skip


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """Several files from one input; the Django docs' recipe."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, list | tuple):
            return [single(file, initial) for file in data]
        return [single(data, initial)] if data else []


class FilesMixin(forms.Form):
    """The `files` field and its checks, shared by the task and update forms."""

    files = MultipleFileField(
        label="Files and screenshots",
        required=False,
        help_text="Images, PDFs and Office files, up to 10 MB each. "
        "You can also paste a screenshot.",
    )

    def clean_files(self):
        files = self.cleaned_data["files"]
        if len(files) > MAX_FILES:
            raise forms.ValidationError(f"Attach at most {MAX_FILES} files at a time.")
        for file in files:
            if Path(file.name).suffix.lower() not in ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    f"{file.name} can't be attached. Use images, PDFs or Office files."
                )
            if file.size > MAX_FILE_SIZE:
                raise forms.ValidationError(
                    f"{file.name} is {filesizeformat(file.size)}. "
                    f"Files can be up to {filesizeformat(MAX_FILE_SIZE)}."
                )
        return files


class AlarmForm(forms.Form):
    """When a task's alarm rings; shared by the task form and the detail page."""

    remind_at = forms.DateTimeField(
        label="Alarm",
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        help_text="Rings in the ERP at this time until the task is done.",
    )
    remind_every = forms.ChoiceField(
        label="Repeat", choices=Repeat.choices, required=False
    )


class TaskForm(FilesMixin, AlarmForm, forms.ModelForm):
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
        fields = [
            "assigned_to", "priority", "description", "due_date",
            "remind_at", "remind_every",
        ]  # fmt: skip
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

    def __init__(self, *args, people=None, **kwargs):
        super().__init__(*args, **kwargs)
        if people is None:  # not an assigner: the task can only be for yourself
            del self.fields["assigned_to"]
        else:
            self.fields["assigned_to"].queryset = people
        if self.instance.pk:  # an existing task's date moves with a reason
            del self.fields["due_date"]
        else:
            self.fields["due_date"].widget.attrs["min"] = (
                timezone.localdate().isoformat()
            )

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


class DateChangeForm(forms.Form):
    due_date = forms.DateField(
        label="New completion date",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        error_messages={"required": "Pick the new completion date."},
    )
    reason = forms.CharField(
        label="Reason",
        max_length=1000,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Why is the date changing?"}
        ),
        error_messages={"required": "Give a reason for the change."},
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Give a reason for the change.")
        return reason


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=Status.choices)


class TaskChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, task):
        return f"P{task.priority} {task.title}"


class UpdateForm(FilesMixin, forms.Form):
    task = TaskChoiceField(
        queryset=Task.objects.none(),
        label="Task",
        empty_label="Choose a task",
        error_messages={"required": "Choose the task this is for."},
    )
    body = forms.CharField(
        label="What did you do?",
        max_length=4000,
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "e.g. Collected the bank statements"}
        ),
        error_messages={"required": "Say what you did."},
    )

    def __init__(self, *args, tasks, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task"].queryset = tasks
        self.fields["files"].widget.attrs["accept"] = ",".join(
            sorted(ALLOWED_EXTENSIONS)
        )

    def clean_body(self):
        body = self.cleaned_data["body"].strip()
        if not body:
            raise forms.ValidationError("Say what you did.")
        return body
