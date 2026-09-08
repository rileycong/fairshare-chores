import secrets
import string

from django.shortcuts import redirect, render

from .forms import CreateHouseholdForm, JoinHouseholdForm
from .models import Household, Roommate

SESSION_KEY = "roommate_id"
MAX_ROOMMATES = 4
JOIN_CODE_ALPHABET = string.ascii_uppercase + "23456789"


def generate_unique_join_code():
    while True:
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(6))
        if not Household.objects.filter(join_code=code).exists():
            return code


def get_roommate(request):
    roommate_id = request.session.get(SESSION_KEY)
    if roommate_id is None:
        return None
    return (
        Roommate.objects.filter(id=roommate_id)
        .select_related("household")
        .first()
    )


class RoommateRequiredMixin:
    def dispatch(self, request, *args, **kwargs):
        self.roommate = get_roommate(request)
        if self.roommate is None:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)


def _render_home(request, create_form=None, join_form=None):
    return render(
        request,
        "home.html",
        {
            "create_form": create_form or CreateHouseholdForm(),
            "join_form": join_form or JoinHouseholdForm(),
        },
    )


def home(request):
    if get_roommate(request) is not None:
        return redirect("chore_list")
    return _render_home(request)


def create_household(request):
    if request.method != "POST":
        return redirect("home")
    form = CreateHouseholdForm(request.POST)
    if not form.is_valid():
        return _render_home(request, create_form=form)

    household = Household.objects.create(join_code=generate_unique_join_code())
    roommate = Roommate(
        household=household,
        display_name=form.cleaned_data["display_name"],
        whatsapp_number=form.cleaned_data["whatsapp_number"],
    )
    roommate.set_pin(form.cleaned_data["pin"])
    roommate.save()
    request.session[SESSION_KEY] = roommate.id
    return redirect("household_code")


def join_household(request):
    if request.method != "POST":
        return redirect("home")
    form = JoinHouseholdForm(request.POST)
    if not form.is_valid():
        return _render_home(request, join_form=form)

    household = form.cleaned_data["join_code"]
    number = form.cleaned_data["whatsapp_number"]
    existing = household.roommates.filter(whatsapp_number=number).first()

    if existing is not None:
        if existing.check_pin(form.cleaned_data["pin"]):
            request.session[SESSION_KEY] = existing.id
            return redirect("chore_list")
        form.add_error(
            "pin",
            "This WhatsApp number is already in this household. Enter its PIN to continue.",
        )
        return _render_home(request, join_form=form)

    if household.roommates.count() >= MAX_ROOMMATES:
        form.add_error(
            None, "This household already has the maximum of 4 roommates."
        )
        return _render_home(request, join_form=form)

    roommate = Roommate(
        household=household,
        display_name=form.cleaned_data["display_name"],
        whatsapp_number=number,
    )
    roommate.set_pin(form.cleaned_data["pin"])
    roommate.save()
    request.session[SESSION_KEY] = roommate.id
    return redirect("chore_list")


def household_code(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    return render(
        request,
        "household_code.html",
        {"roommate": roommate, "join_code": roommate.household.join_code},
    )


def chore_list(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    return render(request, "chores.html", {"roommate": roommate, "chores": []})
