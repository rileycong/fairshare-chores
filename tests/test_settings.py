import pytest

from chores.models import Roommate

from .test_services import make_household, make_roommate


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def settings_payload(**overrides):
    payload = {
        "display_name": "Ada",
        "whatsapp_number": "+15550001",
        "new_pin": "",
        "current_pin": "",
    }
    payload.update(overrides)
    return payload


def make_roommate_with_pin(number="+15550001", pin="1234"):
    household = make_household()
    roommate = make_roommate(household, "Ada", number)
    roommate.set_pin(pin)
    roommate.save()
    return household, roommate


@pytest.mark.django_db
class TestSettingsScreen:
    def test_shows_details_join_code_and_push_placeholder(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        body = client.get("/settings/").content.decode()

        assert household.join_code in body
        assert 'name="display_name"' in body
        assert 'name="whatsapp_number"' in body
        assert 'name="new_pin"' in body
        assert "Web push" in body

    def test_rename_and_number_change(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        response = client.post(
            "/settings/",
            settings_payload(display_name="Ada L", whatsapp_number="+15557777"),
        )

        assert response.status_code == 302
        ada.refresh_from_db()
        assert ada.display_name == "Ada L"
        assert ada.whatsapp_number == "+15557777"

    def test_invalid_number_rejected(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        response = client.post(
            "/settings/", settings_payload(whatsapp_number="15557777")
        )

        assert response.status_code == 200
        assert "international format" in response.content.decode()
        ada.refresh_from_db()
        assert ada.whatsapp_number == "+15550001"

    def test_duplicate_number_in_household_rejected(self, client):
        household, ada = make_roommate_with_pin()
        make_roommate(household, "Ben", "+15550002")
        sign_in(client, ada)

        response = client.post(
            "/settings/", settings_payload(whatsapp_number="+15550002")
        )

        assert response.status_code == 200
        assert "already uses this number" in response.content.decode()
        ada.refresh_from_db()
        assert ada.whatsapp_number == "+15550001"

    def test_new_pin_without_current_pin_rejected(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        response = client.post("/settings/", settings_payload(new_pin="5678"))

        assert response.status_code == 200
        assert "Enter your current PIN" in response.content.decode()
        ada.refresh_from_db()
        assert ada.check_pin("1234")

    def test_new_pin_with_wrong_current_pin_rejected(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        response = client.post(
            "/settings/", settings_payload(new_pin="5678", current_pin="9999")
        )

        assert response.status_code == 200
        assert "Current PIN is incorrect" in response.content.decode()
        ada.refresh_from_db()
        assert ada.check_pin("1234")

    def test_new_pin_with_correct_current_pin_applied(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)

        response = client.post(
            "/settings/", settings_payload(new_pin="5678", current_pin="1234")
        )

        assert response.status_code == 302
        ada.refresh_from_db()
        assert ada.check_pin("5678")
        assert not ada.check_pin("1234")

    def test_signed_out_redirected(self, client):
        response = client.get("/settings/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_chores_screen_links_to_settings(self, client):
        household, ada = make_roommate_with_pin()
        sign_in(client, ada)
        body = client.get("/chores/").content.decode()
        assert 'href="/settings/"' in body
