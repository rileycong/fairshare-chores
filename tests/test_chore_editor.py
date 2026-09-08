from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from chores.models import Chore, Supply

from .test_services import make_chore, make_household, make_roommate, record_completion

PAST = timezone.now() - timedelta(days=1)


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def sign_in_and_get(client, roommate, url):
    sign_in(client, roommate)
    return client.get(url).content.decode()


def chore_payload(**overrides):
    payload = {
        "name": "Take out rubbish",
        "notes": "Bins go out on Thursday",
        "effort": "small",
        "recurrence_kind": "weekly",
        "custom_count": "",
        "custom_unit": "",
        "reminder_time": "09:00",
        "supply": "",
        "new_supply_name": "",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestChoreCreate:
    def test_form_offers_all_fields(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        Supply.objects.create(household=household, name="Bin liners")

        body = sign_in_and_get(client, ada, "/chores/new/")

        for fragment in [
            'name="name"',
            'name="notes"',
            'name="effort"',
            'value="daily"',
            'value="weekly"',
            'value="monthly"',
            'value="custom"',
            'name="custom_count"',
            'name="custom_unit"',
            'name="reminder_time"',
            'name="supply"',
            "Bin liners",
            'name="new_supply_name"',
        ]:
            assert fragment in body

    def test_create_assigns_lowest_total_and_sets_first_due(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ben)
        record_completion(chore, 2)

        sign_in(client, ada)
        response = client.post("/chores/new/", chore_payload())

        assert response.status_code == 302
        created = Chore.objects.get(name="Take out rubbish")
        assert created.household == household
        assert created.assignee == ada
        assert created.status == Chore.Status.ASSIGNED
        local_due = timezone.localtime(created.due_at)
        assert local_due.hour == 9
        assert local_due.date() in (
            timezone.localdate(),
            timezone.localdate() + timedelta(days=1),
        )

    def test_empty_name_shows_field_error(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        response = client.post("/chores/new/", chore_payload(name=""))
        assert response.status_code == 200
        assert Chore.objects.count() == 0

    def test_custom_count_below_one_shows_error(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        response = client.post(
            "/chores/new/",
            chore_payload(
                recurrence_kind="custom", custom_count="0", custom_unit="days"
            ),
        )
        body = response.content.decode()
        assert "at least 1" in body
        assert Chore.objects.count() == 0

    def test_custom_without_unit_shows_error(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        response = client.post(
            "/chores/new/", chore_payload(recurrence_kind="custom", custom_count="2")
        )
        assert "needs a unit" in response.content.decode()
        assert Chore.objects.count() == 0

    def test_new_supply_name_creates_and_links_supply(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)

        client.post(
            "/chores/new/", chore_payload(new_supply_name="Toilet paper")
        )

        supply = Supply.objects.get(name="Toilet paper")
        assert supply.household == household
        assert Chore.objects.get(name="Take out rubbish").supply == supply

    def test_signed_out_redirected(self, client):
        response = client.get("/chores/new/")
        assert response.status_code == 302
        assert response.url == "/"


@pytest.mark.django_db
class TestChoreEdit:
    def test_edit_details_keeps_assignee_and_due_date(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        original_due = chore.due_at
        original_assignee = chore.assignee

        sign_in(client, ada)
        response = client.post(
            f"/chores/{chore.id}/edit/",
            chore_payload(
                name="Take out rubbish",
                notes="Updated notes",
                reminder_time="18:30",
                recurrence_kind="daily",
            ),
        )

        assert response.status_code == 302
        chore.refresh_from_db()
        assert chore.notes == "Updated notes"
        assert str(chore.reminder_time) == "18:30:00"
        assert chore.due_at == original_due
        assert chore.assignee == original_assignee

    def test_changing_recurrence_recomputes_due_from_current_due(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        chore.recurrence_kind = Chore.RecurrenceKind.WEEKLY
        chore.due_at = datetime(2026, 3, 1, 9, 0, tzinfo=dt_timezone.utc)
        chore.save()
        original_assignee = chore.assignee

        sign_in(client, ada)
        client.post(
            f"/chores/{chore.id}/edit/",
            chore_payload(recurrence_kind="monthly"),
        )

        chore.refresh_from_db()
        assert chore.recurrence_kind == Chore.RecurrenceKind.MONTHLY
        assert chore.due_at == datetime(2026, 4, 1, 9, 0, tzinfo=dt_timezone.utc)
        assert chore.assignee == original_assignee

    def test_foreign_household_chore_is_404(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        other = make_household("OTHER1")
        foreign = make_chore(other, make_roommate(other, "Zoe"))

        sign_in(client, ada)
        response = client.get(f"/chores/{foreign.id}/edit/")
        assert response.status_code == 404

        response = client.post(
            f"/chores/{foreign.id}/edit/", chore_payload(name="Hacked")
        )
        assert response.status_code == 404

    def test_supply_dropdown_limited_to_household(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        Supply.objects.create(household=household, name="Ours")
        other = make_household("OTHER1")
        Supply.objects.create(household=other, name="Theirs")

        body = sign_in_and_get(client, ada, f"/chores/new/")

        assert "Ours" in body
        assert "Theirs" not in body

    def test_signed_out_edit_redirected(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada)
        response = client.get(f"/chores/{chore.id}/edit/")
        assert response.status_code == 302
