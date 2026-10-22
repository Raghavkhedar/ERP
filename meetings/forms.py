from django import forms


class BookingForm(forms.Form):
    topic = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Leave request"}),
        help_text="What is the meeting about?",
    )
