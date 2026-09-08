from datetime import timedelta

import json
import os
import secrets
import string

from django.contrib.staticfiles import finders
from django.core.paginator import Paginator
from django.http import (
    FileResponse,
    Http404,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    ChoreForm,
    CreateHouseholdForm,
    JoinHouseholdForm,
    SettingsForm,
)
from .models import (
    Chore,
    HistoryRecord,
    Household,
    PushSubscription,
    Roommate,
    Supply,
    SwapRequest,
)
from .services import (
    CompletionError,
    SwapError,
    complete_chore as complete_chore_service,
    next_due,
    pick_assignee,
    request_swap as request_swap_service,
    respond_to_swap as respond_to_swap_service,
)

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

    chores = list(
        roommate.household.chores.select_related("assignee").order_by("due_at")
    )
    now = timezone.now()
    grouped = {"overdue": [], "swap_requested": [], "assigned": []}
    for chore in chores:
        if chore.status == Chore.Status.SWAP_REQUESTED:
            grouped["swap_requested"].append(chore)
        elif chore.due_at < now:
            grouped["overdue"].append(chore)
        else:
            grouped["assigned"].append(chore)

    return render(
        request,
        "chores.html",
        {
            "roommate": roommate,
            "has_chores": bool(chores),
            "other_roommates": roommate.household.roommates.exclude(id=roommate.id),
            "incoming_swaps": SwapRequest.objects.filter(
                target=roommate, status=SwapRequest.Status.PENDING
            ).select_related("chore", "requested_by"),
            "groups": [
                ("overdue", "Overdue", grouped["overdue"]),
                ("swap_requested", "Swap requested", grouped["swap_requested"]),
                ("assigned", "Assigned", grouped["assigned"]),
            ],
        },
    )


def request_swap_view(request, chore_id):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    chore = get_object_or_404(Chore, id=chore_id, household=roommate.household)
    if request.method != "POST":
        return redirect("chore_list")
    raw_target = request.POST.get("target_id")
    target = None
    if raw_target is not None and str(raw_target).isdigit():
        target = Roommate.objects.filter(
            id=int(raw_target), household=roommate.household
        ).first()
    try:
        request_swap_service(chore, roommate, target)
    except SwapError:
        return HttpResponseForbidden(
            "Swap request failed. Choose a different roommate for this chore."
        )
    return redirect("chore_list")


def respond_swap_view(request, swap_id, decision):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    swap = get_object_or_404(
        SwapRequest, id=swap_id, chore__household=roommate.household
    )
    if request.method != "POST":
        return redirect("chore_list")
    try:
        respond_to_swap_service(swap, roommate, accept=(decision == "accept"))
    except SwapError:
        return HttpResponseForbidden("Only the chosen roommate can respond.")
    return redirect("chore_list")


def supplies_list(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    supplies = roommate.household.supplies.order_by("name")
    return render(
        request, "supplies.html", {"roommate": roommate, "supplies": supplies}
    )


def toggle_supply(request, supply_id):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    supply = get_object_or_404(
        Supply, id=supply_id, household=roommate.household
    )
    if request.method != "POST":
        return redirect("supplies_list")
    supply.restocked = not supply.restocked
    supply.save(update_fields=["restocked"])
    return redirect("supplies_list")


def history_list(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    records = (
        HistoryRecord.objects.filter(chore__household=roommate.household)
        .select_related("chore", "assignee")
        .order_by("-completed_at")
    )
    paginator = Paginator(records, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "history.html",
        {"roommate": roommate, "page_obj": page_obj},
    )


def service_worker(request):
    return render(request, "service_worker.js", content_type="application/javascript")


def manifest(request):
    return render(
        request,
        "manifest.webmanifest",
        content_type="application/manifest+json",
    )


def app_icon(request, size):
    if size not in (192, 512):
        raise Http404("unsupported icon size")
    path = finders.find(f"icons/icon-{size}.png")
    if path is None:
        raise Http404("icon not found")
    return FileResponse(open(path, "rb"), content_type="image/png")


def offline(request):
    return render(request, "offline.html")


@require_POST
def push_subscribe(request):
    roommate = get_roommate(request)
    if roommate is None:
        return JsonResponse({"error": "not signed in"}, status=403)
    try:
        data = json.loads(request.body)
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh = keys["p256dh"]
        auth = keys["auth"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return HttpResponseBadRequest("invalid subscription payload")

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "roommate": roommate,
            "p256dh": p256dh,
            "auth": auth,
        },
    )
    return JsonResponse({"ok": True})


def settings_view(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")

    if request.method == "POST":
        form = SettingsForm(request.POST, instance=roommate)
        if form.is_valid():
            roommate = form.save(commit=False)
            new_pin = form.cleaned_data.get("new_pin")
            if new_pin:
                roommate.set_pin(new_pin)
            roommate.save()
            return redirect("settings")
    else:
        form = SettingsForm(instance=roommate)

    return render(
        request,
        "settings.html",
        {
            "roommate": roommate,
            "form": form,
            "join_code": roommate.household.join_code,
            "vapid_public_key": os.environ.get("VAPID_PUBLIC_KEY", ""),
        },
    )


def _first_due(reminder_time):
    now_local = timezone.localtime(timezone.now())
    candidate = now_local.replace(
        hour=reminder_time.hour, minute=reminder_time.minute, second=0, microsecond=0
    )
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate


def _apply_new_supply(form, household, chore):
    new_supply_name = form.cleaned_data.get("new_supply_name")
    if new_supply_name:
        supply, _ = Supply.objects.get_or_create(
            household=household, name=new_supply_name
        )
        chore.supply = supply
    return chore


def chore_create(request):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")

    if request.method == "POST":
        form = ChoreForm(request.POST, household=roommate.household)
        if form.is_valid():
            chore = form.save(commit=False)
            chore.household = roommate.household
            _apply_new_supply(form, roommate.household, chore)
            chore.due_at = _first_due(form.cleaned_data["reminder_time"])
            chore.status = Chore.Status.ASSIGNED
            chore.assignee = pick_assignee(roommate.household)
            chore.save()
            return redirect("chore_list")
    else:
        form = ChoreForm(household=roommate.household)

    return render(request, "chore_form.html", {"roommate": roommate, "form": form})


RECURRENCE_FIELDS = ("recurrence_kind", "custom_count", "custom_unit")


def chore_edit(request, chore_id):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    chore = get_object_or_404(Chore, id=chore_id, household=roommate.household)

    if request.method == "POST":
        previous = {field: getattr(chore, field) for field in RECURRENCE_FIELDS}
        form = ChoreForm(request.POST, instance=chore, household=roommate.household)
        if form.is_valid():
            chore = form.save(commit=False)
            _apply_new_supply(form, roommate.household, chore)
            changed = any(
                getattr(chore, field) != previous[field] for field in RECURRENCE_FIELDS
            )
            if changed:
                chore.due_at = next_due(chore)
            chore.save()
            return redirect("chore_list")
    else:
        form = ChoreForm(instance=chore, household=roommate.household)

    return render(
        request,
        "chore_form.html",
        {"roommate": roommate, "form": form, "chore": chore},
    )


def complete_chore_view(request, chore_id):
    roommate = get_roommate(request)
    if roommate is None:
        return redirect("home")
    chore = get_object_or_404(Chore, id=chore_id, household=roommate.household)
    if request.method != "POST":
        return redirect("chore_list")
    try:
        complete_chore_service(chore, roommate)
    except CompletionError:
        return HttpResponseForbidden(
            "Only the current assignee can complete this chore."
        )
    return redirect("chore_list")
