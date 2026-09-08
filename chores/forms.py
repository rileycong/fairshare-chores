from django import forms

WHATSAPP_REGEX = r"^\+[1-9]\d{7,14}$"


class WhatsAppNumberField(forms.CharField):
    default_error_messages = {
        "invalid": "Enter a WhatsApp number in international format, e.g. +15551234567."
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("max_length", 20)
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        if value and not self._is_e164(value):
            raise forms.ValidationError(self.default_error_messages["invalid"])
        return value

    @staticmethod
    def _is_e164(value):
        return value.startswith("+") and value[1:].isdigit() and 8 <= len(value[1:]) <= 15


class CreateHouseholdForm(forms.Form):
    display_name = forms.CharField(max_length=80)
    pin = forms.CharField(min_length=4, max_length=8, widget=forms.PasswordInput)
    whatsapp_number = WhatsAppNumberField()


class JoinHouseholdForm(forms.Form):
    join_code = forms.CharField(max_length=8)
    display_name = forms.CharField(max_length=80)
    pin = forms.CharField(min_length=4, max_length=8, widget=forms.PasswordInput)
    whatsapp_number = WhatsAppNumberField()

    def clean_join_code(self):
        from .models import Household

        code = self.cleaned_data["join_code"].strip().upper()
        try:
            return Household.objects.get(join_code=code)
        except Household.DoesNotExist:
            raise forms.ValidationError("Unknown join code. Check with your roommate.")
