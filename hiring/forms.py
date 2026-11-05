from django import forms

from people.models import phone_key

from .models import Requisition


class RequisitionForm(forms.ModelForm):
    # The version the form was opened at; see services.save_requisition.
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Requisition
        fields = ["department", "profile", "headcount", "site", "needed_by"]
        widgets = {
            "needed_by": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
        }


class SourceForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    name = forms.CharField(max_length=200)
    phone = forms.CharField(max_length=30)
    email = forms.EmailField(required=False)
    source = forms.CharField(
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"list": "sources"}),
    )

    def __init__(self, *args, requisitions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisition"].queryset = requisitions

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if len(phone_key(phone)) < 10:
            raise forms.ValidationError("Enter a phone number with at least 10 digits.")
        return phone


class ImportForm(forms.Form):
    requisition = forms.ModelChoiceField(Requisition.objects.none())
    source = forms.CharField(
        max_length=120,
        required=False,
        help_text="Used for rows with no Source column.",
        widget=forms.TextInput(attrs={"list": "sources"}),
    )
    sheet = forms.FileField(label="Excel file (.xlsx)")

    def __init__(self, *args, requisitions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requisition"].queryset = requisitions
