from django import forms

from .models import Chore, Roommate, Supply

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


class SettingsForm(forms.ModelForm):
    whatsapp_number = WhatsAppNumberField()
    new_pin = forms.CharField(
        min_length=4,
        max_length=8,
        required=False,
        widget=forms.PasswordInput,
        help_text="Leave blank to keep your current PIN",
    )
    current_pin = forms.CharField(
        max_length=8,
        required=False,
        widget=forms.PasswordInput,
        help_text="Required only when setting a new PIN",
    )

    class Meta:
        model = Roommate
        fields = ["display_name", "whatsapp_number"]

    def clean_whatsapp_number(self):
        number = self.cleaned_data.get("whatsapp_number", "")
        query = Roommate.objects.filter(
            household_id=self.instance.household_id, whatsapp_number=number
        )
        if self.instance.pk:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise forms.ValidationError(
                "Another roommate in this household already uses this number."
            )
        return number

    def clean(self):
        cleaned = super().clean()
        new_pin = cleaned.get("new_pin")
        current_pin = cleaned.get("current_pin")
        if new_pin:
            if not current_pin:
                self.add_error(
                    "current_pin", "Enter your current PIN to set a new one."
                )
            elif self.instance.pk and not self.instance.check_pin(current_pin):
                self.add_error("current_pin", "Current PIN is incorrect.")
        return cleaned


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
