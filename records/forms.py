from django import forms

from .models import Person


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "person_type",
            "name",
            "email",
            "phone",
            "department",
            "course",
            "year",
            "designation",
            "status",
        ]


class PeopleUploadForm(forms.Form):
    upload_file = forms.FileField(
        label="Choose a people file",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".csv,.xlsx,.json,.txt,.docx,.pdf,.png,.jpg,.jpeg,"
                    ".webp,.bmp,.tif,.tiff"
                ),
                "class": "form-control",
            }
        ),
    )
