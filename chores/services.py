from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import Sum

from .models import Chore, Household, Roommate


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


def pick_assignee(household: Household) -> Roommate | None:
    roommates = list(household.roommates.order_by("id"))
    if not roommates:
        return None

    totals = {
        roommate.id: (
            roommate.history_records.aggregate(total=Sum("effort_points"))["total"]
            or 0
        )
        for roommate in roommates
    }
    lowest = min(totals.values())
    tied = [roommate for roommate in roommates if totals[roommate.id] == lowest]

    if len(tied) == 1:
        return tied[0]

    chosen = tied[household.rotation_counter % len(tied)]
    household.rotation_counter += 1
    household.save(update_fields=["rotation_counter"])
    return chosen
