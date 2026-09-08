from datetime import timedelta

import pytest
from django.db.models import Sum
from django.utils import timezone

from chores.models import Chore, HistoryRecord, Supply
from chores.services import CompletionError, complete_chore

from .test_services import make_chore, make_household, make_roommate


@pytest.mark.django_db
class TestCompleteChore:
    def test_non_assignee_cannot_complete(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada)

        with pytest.raises(CompletionError):
            complete_chore(chore, ben)

        assert HistoryRecord.objects.count() == 0

    def test_unassigned_chore_cannot_be_completed(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, None)

        with pytest.raises(CompletionError):
            complete_chore(chore, ada)

    def test_completion_writes_history_record(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        chore.effort = Chore.Effort.LARGE
        chore.save()
        due_at = chore.due_at

        before = timezone.now()
        complete_chore(chore, ada)
        after = timezone.now()

        record = HistoryRecord.objects.get()
        assert record.chore == chore
        assert record.assignee == ada
        assert record.effort_points == 3
        assert record.due_at == due_at
        assert before <= record.completed_at <= after
        assert record.swapped is False

    def test_linked_supply_becomes_restocked(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        supply = Supply.objects.create(household=household, name="Dish soap")
        chore = make_chore(household, ada)
        chore.supply = supply
        chore.save()

        complete_chore(chore, ada)

        supply.refresh_from_db()
        assert supply.restocked is True

    def test_completion_without_supply_is_fine(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        complete_chore(chore, ada)
        assert HistoryRecord.objects.count() == 1

    def test_chore_moves_to_next_occurrence_with_new_assignee(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada)
        chore.recurrence_kind = Chore.RecurrenceKind.DAILY
        chore.due_at = timezone.now().replace(microsecond=0)
        original_due = chore.due_at
        chore.save()

        complete_chore(chore, ada)

        chore.refresh_from_db()
        assert chore.due_at > original_due
        assert chore.status == Chore.Status.ASSIGNED
        assert chore.assignee == ben

    def test_completers_point_total_reflects_new_record(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        chore.effort = Chore.Effort.LARGE
        chore.save()

        complete_chore(chore, ada)

        total = ada.history_records.aggregate(t=Sum("effort_points"))["t"]
        assert total == 3

    def test_cadence_anchored_to_original_due_not_completion_time(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        chore.recurrence_kind = Chore.RecurrenceKind.WEEKLY
        chore.due_at = timezone.now() - timedelta(days=10)
        original_due = chore.due_at
        chore.save()

        complete_chore(chore, ada)

        chore.refresh_from_db()
        assert chore.due_at - original_due == timedelta(days=7)
