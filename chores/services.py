from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Chore, HistoryRecord, Household, Roommate, SwapRequest


class CompletionError(Exception):
    pass


class SwapError(Exception):
    pass


def next_due(chore: Chore):
    due_at = chore.due_at
    kind = chore.recurrence_kind

    if kind == Chore.RecurrenceKind.DAILY:
        return due_at + timedelta(days=1)
    if kind == Chore.RecurrenceKind.WEEKLY:
        return due_at + timedelta(weeks=1)
    if kind == Chore.RecurrenceKind.MONTHLY:
        return due_at + relativedelta(months=1)
    if kind == Chore.RecurrenceKind.CUSTOM:
        if not chore.custom_count or not chore.custom_unit:
            raise ValueError("custom recurrence needs custom_count and custom_unit")
        count = chore.custom_count
        if chore.custom_unit == Chore.CustomUnit.HOURS:
            return due_at + timedelta(hours=count)
        if chore.custom_unit == Chore.CustomUnit.DAYS:
            return due_at + timedelta(days=count)
        if chore.custom_unit == Chore.CustomUnit.WEEKS:
            return due_at + timedelta(weeks=count)
        if chore.custom_unit == Chore.CustomUnit.MONTHS:
            return due_at + relativedelta(months=count)
    raise ValueError(f"unknown recurrence kind: {kind}")


def schedule_next(chore: Chore) -> Chore:
    chore.due_at = next_due(chore)
    chore.assignee = pick_assignee(chore.household)
    chore.status = Chore.Status.ASSIGNED
    chore.save()
    return chore


def _is_swapped_assignment(chore: Chore, roommate: Roommate) -> bool:
    accepted = chore.swap_requests.filter(
        status=SwapRequest.Status.ACCEPTED, target=roommate
    )
    last_completed = chore.history_records.order_by("-completed_at").first()
    if last_completed is not None:
        accepted = accepted.filter(responded_at__gt=last_completed.completed_at)
    return accepted.exists()


def complete_chore(chore: Chore, roommate: Roommate) -> Chore:
    if chore.assignee_id is None or roommate.id != chore.assignee_id:
        raise CompletionError("only the current assignee can complete a chore")

    with transaction.atomic():
        HistoryRecord.objects.create(
            chore=chore,
            assignee=roommate,
            effort_points=chore.effort_points,
            due_at=chore.due_at,
            completed_at=timezone.now(),
            swapped=_is_swapped_assignment(chore, roommate),
        )
        if chore.supply_id and not chore.supply.restocked:
            chore.supply.restocked = True
            chore.supply.save(update_fields=["restocked"])
        schedule_next(chore)
    return chore


def request_swap(chore: Chore, requester: Roommate, target: Roommate) -> SwapRequest:
    if chore.assignee_id != requester.id:
        raise SwapError("only the current assignee can request a swap")
    if target is None:
        raise SwapError("choose a roommate to swap with")
    if target.id == requester.id:
        raise SwapError("choose a different roommate to swap with")
    if target.household_id != chore.household_id:
        raise SwapError("target must be in the same household")
    if chore.swap_requests.filter(status=SwapRequest.Status.PENDING).exists():
        raise SwapError("a swap is already pending for this chore")
    swap = SwapRequest.objects.create(
        chore=chore, requested_by=requester, target=target
    )
    chore.status = Chore.Status.SWAP_REQUESTED
    chore.save(update_fields=["status"])
    return swap


def respond_to_swap(swap_request: SwapRequest, responder: Roommate, accept: bool):
    if swap_request.status != SwapRequest.Status.PENDING:
        raise SwapError("this swap request was already answered")
    if responder.id != swap_request.target_id:
        raise SwapError("only the chosen roommate can respond")
    swap_request.status = (
        SwapRequest.Status.ACCEPTED if accept else SwapRequest.Status.DECLINED
    )
    swap_request.responded_at = timezone.now()
    swap_request.save()

    chore = swap_request.chore
    if accept:
        chore.assignee = swap_request.target
    chore.status = Chore.Status.ASSIGNED
    chore.save()
    return swap_request


def _tied_leaders(household):
    roommates = list(household.roommates.order_by("id"))
    if not roommates:
        return []
    totals = {
        roommate.id: (
            roommate.history_records.aggregate(total=Sum("effort_points"))["total"]
            or 0
        )
        for roommate in roommates
    }
    lowest = min(totals.values())
    return [roommate for roommate in roommates if totals[roommate.id] == lowest]


def preview_assignee(household: Household) -> Roommate | None:
    tied = _tied_leaders(household)
    if not tied:
        return None
    return tied[household.rotation_counter % len(tied)]


def pick_assignee(household: Household) -> Roommate | None:
    tied = _tied_leaders(household)
    if not tied:
        return None
    if len(tied) == 1:
        return tied[0]
    chosen = tied[household.rotation_counter % len(tied)]
    household.rotation_counter += 1
    household.save(update_fields=["rotation_counter"])
    return chosen
