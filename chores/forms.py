from django import forms

from .models import Chore, Supply

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


class ChoreForm(forms.ModelForm):
    new_supply_name = forms.CharField(
        max_length=120,
        required=False,
        help_text="Or add a new supply by name",
    )

    class Meta:
        model = Chore
        fields = [
            "name",
            "notes",
            "effort",
            "recurrence_kind",
            "custom_count",
            "custom_unit",
            "reminder_time",
            "supply",
        ]
        widgets = {
            "custom_count": forms.NumberInput(attrs={"min": 1}),
        }

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        if household is not None:
            self.fields["supply"].queryset = household.supplies.all()
        else:
            self.fields["supply"].queryset = Supply.objects.none()
        self.fields["supply"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("recurrence_kind") == Chore.RecurrenceKind.CUSTOM:
            count = cleaned.get("custom_count")
            unit = cleaned.get("custom_unit")
            if count is None:
                self.add_error(
                    "custom_count", "Custom recurrence needs an interval count."
                )
            elif count < 1:
                self.add_error("custom_count", "Interval must be at least 1.")
            if not unit:
                self.add_error("custom_unit", "Custom recurrence needs a unit.")
        return cleaned
