import pytest
from django.utils import timezone

from chores.models import Chore, HistoryRecord
from chores.services import pick_assignee


def make_household(join_code="ABCD12"):
    from chores.models import Household

    return Household.objects.create(join_code=join_code)


def make_roommate(household, name, number="+15550001"):
    from chores.models import Roommate

    return Roommate.objects.create(
        household=household, display_name=name, pin="", whatsapp_number=number
    )


def make_chore(household, assignee, name="Dishes"):
    return Chore.objects.create(
        household=household,
        name=name,
        reminder_time="09:00",
        assignee=assignee,
        due_at=timezone.now(),
    )


def record_completion(chore, points):
    HistoryRecord.objects.create(
        chore=chore,
        assignee=chore.assignee,
        effort_points=points,
        due_at=chore.due_at,
        completed_at=timezone.now(),
    )


@pytest.mark.django_db
class TestPickAssignee:
    def test_picks_roommate_with_lowest_total(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ben)
        record_completion(chore, 3)

        assert pick_assignee(household) == ada

    def test_returns_roommate_instance(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        assert type(pick_assignee(household)) is type(ada)

    def test_no_history_assigns_without_error(self):
        household = make_household()
        make_roommate(household, "Ada")
        make_roommate(household, "Ben", "+15550002")
        assert pick_assignee(household) is not None

    def test_three_consecutive_ties_rotate_through_each_roommate(self):
        household = make_household()
        roommates = [
            make_roommate(household, "Ada"),
            make_roommate(household, "Ben", "+15550002"),
            make_roommate(household, "Cal", "+15550003"),
        ]
        picks = [pick_assignee(household) for _ in range(3)]
        assert picks == roommates

    def test_rotation_counter_increments_on_each_tie_break(self):
        household = make_household()
        make_roommate(household, "Ada")
        make_roommate(household, "Ben", "+15550002")
        make_roommate(household, "Cal", "+15550003")

        pick_assignee(household)
        assert household.rotation_counter == 1
        pick_assignee(household)
        assert household.rotation_counter == 2

    def test_rotation_continues_after_new_completions(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        cal = make_roommate(household, "Cal", "+15550003")

        pick_assignee(household)
        pick_assignee(household)

        chore = make_chore(household, ada)
        record_completion(chore, 2)
        chore = make_chore(household, ben)
        record_completion(chore, 1)

        assert pick_assignee(household) == cal

    def test_tie_between_two_rotates_back_to_first(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")

        first = pick_assignee(household)
        second = pick_assignee(household)
        third = pick_assignee(household)

        assert [first, second, third] == [ada, ben, ada]

    @pytest.mark.parametrize("size", [2, 3, 4])
    def test_works_for_households_of_two_three_and_four(self, size):
        household = make_household()
        roommates = [
            make_roommate(household, f"R{i}", f"+1555000{i}")
            for i in range(1, size + 1)
        ]
        chore = make_chore(household, roommates[-1])
        record_completion(chore, 3)

        assert pick_assignee(household) == roommates[0]

    @pytest.mark.parametrize("size", [2, 3, 4])
    def test_all_tied_roommates_get_picked_before_any_repeat(self, size):
        household = make_household()
        roommates = [
            make_roommate(household, f"R{i}", f"+1555000{i}")
            for i in range(1, size + 1)
        ]

        picks = [pick_assignee(household) for _ in range(size)]
        assert picks == roommates

    def test_single_roommate_household(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        assert pick_assignee(household) == ada

    def test_household_without_roommates_returns_none(self):
        assert pick_assignee(make_household()) is None
