import pytest

from chores.models import Supply

from .test_services import make_household, make_roommate


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


@pytest.mark.django_db
class TestSuppliesScreen:
    def test_lists_household_supplies_with_state(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        restocked = Supply.objects.create(
            household=household, name="Toilet paper", restocked=True
        )
        low = Supply.objects.create(household=household, name="Dish soap")

        sign_in(client, ada)
        body = client.get("/supplies/").content.decode()

        assert "Toilet paper" in body
        assert "Dish soap" in body
        assert f'action="/supplies/{restocked.id}/toggle/"' in body
        assert f'action="/supplies/{low.id}/toggle/"' in body
        assert "Not restocked" in body

    def test_other_household_supplies_invisible(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        other = make_household("OTHER1")
        Supply.objects.create(household=other, name="Their milk")

        sign_in(client, ada)
        body = client.get("/supplies/").content.decode()

        assert "Their milk" not in body

    def test_empty_state_prompts_chore_editor(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        body = client.get("/supplies/").content.decode()
        assert "No supplies yet" in body

    def test_any_roommate_can_toggle_restocked(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        supply = Supply.objects.create(household=household, name="Paper towels")

        sign_in(client, ben)
        response = client.post(f"/supplies/{supply.id}/toggle/")

        assert response.status_code == 302
        supply.refresh_from_db()
        assert supply.restocked is True

        sign_in(client, ada)
        client.post(f"/supplies/{supply.id}/toggle/")
        supply.refresh_from_db()
        assert supply.restocked is False

    def test_toggle_other_household_supply_is_404(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        other = make_household("OTHER1")
        foreign = Supply.objects.create(household=other, name="Foreign supply")

        sign_in(client, ada)
        response = client.post(f"/supplies/{foreign.id}/toggle/")

        assert response.status_code == 404
        foreign.refresh_from_db()
        assert foreign.restocked is False

    def test_toggle_get_request_does_not_change_state(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        supply = Supply.objects.create(household=household, name="Sponges")

        sign_in(client, ada)
        response = client.get(f"/supplies/{supply.id}/toggle/")

        assert response.status_code == 302
        supply.refresh_from_db()
        assert supply.restocked is False

    def test_signed_out_redirected(self, client):
        response = client.get("/supplies/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_supply_created_in_chore_editor_appears(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)
        client.post(
            "/chores/new/",
            {
                "name": "Buy milk",
                "notes": "",
                "effort": "small",
                "recurrence_kind": "weekly",
                "custom_count": "",
                "custom_unit": "",
                "reminder_time": "09:00",
                "supply": "",
                "new_supply_name": "Milk",
            },
        )

        body = client.get("/supplies/").content.decode()

        assert "Milk" in body
        assert Supply.objects.filter(household=household, name="Milk").exists()
