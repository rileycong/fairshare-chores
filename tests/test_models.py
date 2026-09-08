import pytest
from django.apps import apps
from django.contrib import admin

from chores.models import (
    Chore,
    HistoryRecord,
    Household,
    PushSubscription,
    Roommate,
    SwapRequest,
    Supply,
)

ALL_MODELS = [
    Household,
    Roommate,
    Chore,
    SwapRequest,
    Supply,
    HistoryRecord,
    PushSubscription,
]


def make_household(join_code="ABCD12"):
    return Household.objects.create(join_code=join_code)


def make_roommate(household, name, number="+15550001"):
    return Roommate.objects.create(
        household=household,
        display_name=name,
        pin="",
        whatsapp_number=number,
    )


@pytest.mark.django_db
class TestModelsExist:
    def test_all_seven_models_are_installed(self):
        for model in ALL_MODELS:
            assert apps.is_installed(model._meta.app_label)
            assert model.objects.model is model

    def test_all_seven_models_are_registered_in_admin(self):
        for model in ALL_MODELS:
            assert admin.site.is_registered(model)


@pytest.mark.django_db
class TestHousehold:
    def test_join_code_is_unique(self):
        make_household("SAME01")
        with pytest.raises(Exception):
            make_household("SAME01")

    def test_rotation_counter_defaults_to_zero(self):
        assert make_household().rotation_counter == 0


@pytest.mark.django_db
class TestRoommate:
    def test_whatsapp_number_unique_within_household(self):
        household = make_household()
        make_roommate(household, "Ada")
        with pytest.raises(Exception):
            make_roommate(household, "Grace", "+15550001")

    def test_same_number_allowed_in_different_households(self):
        make_roommate(make_household("HH0001"), "Ada")
        make_roommate(make_household("HH0002"), "Grace")

    def test_pin_is_stored_hashed(self):
        roommate = make_roommate(make_household(), "Ada")
        roommate.set_pin("1234")
        roommate.save()
        assert roommate.pin != "1234"
        assert roommate.pin.startswith("pbkdf2_")
        assert roommate.check_pin("1234")
        assert not roommate.check_pin("9999")


@pytest.mark.django_db
class TestChore:
    def test_effort_points_are_fixed(self):
        household = make_household()
        assignee = make_roommate(household, "Ada")
        due = "2026-09-08T09:00:00Z"
        cases = {"small": 1, "medium": 2, "large": 3}
        for effort, points in cases.items():
            chore = Chore.objects.create(
                household=household,
                name=f"Chore {effort}",
                effort=effort,
                reminder_time="09:00",
                assignee=assignee,
                due_at=due,
            )
            assert chore.effort_points == points

    def test_status_defaults_to_assigned_and_excludes_completed(self):
        assert Chore.Status.ASSIGNED == "assigned"
        assert "completed" not in Chore.Status.values
        assert set(Chore.Status.values) == {"assigned", "swap_requested", "overdue"}

    def test_recurrence_choices_cover_presets_and_custom(self):
        assert set(Chore.RecurrenceKind.values) == {
            "daily",
            "weekly",
            "monthly",
            "custom",
        }
        assert set(Chore.CustomUnit.values) == {"hours", "days", "weeks", "months"}

    def test_assignee_and_supply_are_optional(self):
        household = make_household()
        chore = Chore.objects.create(
            household=household,
            name="Mop",
            reminder_time="09:00",
            due_at="2026-09-08T09:00:00Z",
        )
        assert chore.assignee is None
        assert chore.supply is None


@pytest.mark.django_db
class TestRelatedModels:
    def test_swap_request_defaults_to_pending(self):
        household = make_household()
        requester = make_roommate(household, "Ada")
        target = make_roommate(household, "Ben", "+15550002")
        chore = Chore.objects.create(
            household=household,
            name="Dishes",
            reminder_time="09:00",
            due_at="2026-09-08T09:00:00Z",
            assignee=requester,
        )
        swap = SwapRequest.objects.create(
            chore=chore, requested_by=requester, target=target
        )
        assert swap.status == SwapRequest.Status.PENDING

    def test_supply_defaults_to_not_restocked(self):
        supply = Supply.objects.create(household=make_household(), name="Soap")
        assert supply.restocked is False

    def test_history_record_fields(self):
        household = make_household()
        assignee = make_roommate(household, "Ada")
        chore = Chore.objects.create(
            household=household,
            name="Bins",
            reminder_time="09:00",
            due_at="2026-09-08T09:00:00Z",
            assignee=assignee,
        )
        record = HistoryRecord.objects.create(
            chore=chore,
            assignee=assignee,
            effort_points=chore.effort_points,
            due_at="2026-09-08T09:00:00Z",
            completed_at="2026-09-08T10:00:00Z",
        )
        assert record.swapped is False
        assert record.effort_points == 2

    def test_push_subscription_endpoint_is_unique(self):
        roommate = make_roommate(make_household(), "Ada")
        PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/sub/1",
            p256dh="key-a",
            auth="auth-a",
        )
        with pytest.raises(Exception):
            PushSubscription.objects.create(
                roommate=roommate,
                endpoint="https://push.example.com/sub/1",
                p256dh="key-b",
                auth="auth-b",
            )
