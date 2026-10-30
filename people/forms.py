from django import forms

from .models import Person, phone_key

FIELDS = [
    "name",
    "phone",
    "email",
    "address",
    "current_employer",
    "current_salary",
    "expected_salary",
    "experience_years",
    "joining_period",
    "contact_status",
    "priority",
]


class PersonForm(forms.ModelForm):
    # The version the form was opened at; see services.save_person.
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Person
        fields = FIELDS
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if len(phone_key(phone)) < 10:
            raise forms.ValidationError("Enter a phone number with at least 10 digits.")
        return phone
