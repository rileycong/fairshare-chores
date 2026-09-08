from django.db.models import Sum

from .models import Household, Roommate


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
