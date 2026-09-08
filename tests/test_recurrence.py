from datetime import datetime, timezone as dt_timezone

import pytest

from chores.models import Chore
from chores.services import next_due, schedule_next

from .test_services import make_chore, make_household, make_roommate, record_completion


def dt(year, month, day, hour=9):
    return datetime(year, month, day, hour, 0, tzinfo=dt_timezone.utc)


def make_custom_chore(household, assignee, count, unit, due):
    return Chore.objects.create(
        household=household,
        name="Water plants",
        recurrence_kind=Chore.RecurrenceKind.CUSTOM,
        custom_count=count,
        custom_unit=unit,
        reminder_time="09:00",
        assignee=assignee,
        due_at=due,
    )


@pytest.mark.django_db
class TestNextDue:
    def test_daily_advances_one_calendar_day(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.DAILY
        chore.due_at = dt(2026, 1, 1)
        assert next_due(chore) == dt(2026, 1, 2)

    def test_weekly_advances_one_calendar_week(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.WEEKLY
        chore.due_at = dt(2026, 1, 1)
        assert next_due(chore) == dt(2026, 1, 8)

    def test_monthly_advances_one_calendar_month(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.MONTHLY
        chore.due_at = dt(2026, 3, 15)
        assert next_due(chore) == dt(2026, 4, 15)

    def test_monthly_clamps_month_end_to_valid_day(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.MONTHLY
        chore.due_at = dt(2026, 1, 31)
        assert next_due(chore) == dt(2026, 2, 28)

    def test_monthly_from_feb_28_advances_to_mar_28(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.MONTHLY
        chore.due_at = dt(2026, 2, 28)
        assert next_due(chore) == dt(2026, 3, 28)

    @pytest.mark.parametrize(
        "count,unit,expected",
        [
            (2, "hours", dt(2026, 1, 1, 11)),
            (3, "days", dt(2026, 1, 4)),
            (2, "weeks", dt(2026, 1, 15)),
            (2, "months", dt(2026, 3, 1)),
        ],
    )
    def test_custom_recurrence_advances_by_n_units(self, count, unit, expected):
        household = make_household()
        chore = make_custom_chore(
            household, make_roommate(household, "Ada"), count, unit, dt(2026, 1, 1)
        )
        assert next_due(chore) == expected

    def test_custom_without_count_or_unit_raises(self):
        household = make_household()
        chore = make_custom_chore(
            household, make_roommate(household, "Ada"), None, None, dt(2026, 1, 1)
        )
        with pytest.raises(ValueError):
            next_due(chore)


@pytest.mark.django_db
class TestScheduleNext:
    def test_advances_due_date_and_resets_status(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.WEEKLY
        chore.status = Chore.Status.OVERDUE
        chore.due_at = dt(2026, 1, 1)
        chore.save()

        schedule_next(chore)

        assert chore.due_at == dt(2026, 1, 8)
        assert chore.status == Chore.Status.ASSIGNED

    def test_next_assignee_is_picked_by_lowest_total(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ben)
        record_completion(chore, 3)

        chore.recurrence_kind = Chore.RecurrenceKind.DAILY
        chore.due_at = dt(2026, 1, 1)
        schedule_next(chore)

        assert chore.assignee == ada

    def test_cadence_stays_anchored_after_late_completion(self):
        household = make_household()
        chore = make_chore(household, make_roommate(household, "Ada"))
        chore.recurrence_kind = Chore.RecurrenceKind.MONTHLY
        chore.due_at = dt(2026, 1, 1)
        chore.save()

        record_completion(chore, 2)
        assert chore.due_at == dt(2026, 1, 1)
        schedule_next(chore)
        assert chore.due_at == dt(2026, 2, 1)
