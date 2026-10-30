from django import forms

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
