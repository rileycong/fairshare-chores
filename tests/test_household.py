import pytest

from chores.models import Household, Roommate
from chores.views import MAX_ROOMMATES

from .test_services import make_household, make_roommate

CREATE_PAYLOAD = {
    "display_name": "Ada",
    "pin": "1234",
    "whatsapp_number": "+15550001",
}

JOIN_PAYLOAD = {
    "join_code": "",
    "display_name": "Ben",
    "pin": "5678",
    "whatsapp_number": "+15550002",
}


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


@pytest.mark.django_db
class TestWelcomeScreen:
    def test_home_shows_create_and_join_paths(self, client):
        response = client.get("/")
        assert response.status_code == 200
        body = response.content.decode()
        assert 'action="/create/"' in body
        assert 'action="/join/"' in body

    def test_base_template_has_viewport_meta(self, client):
        body = client.get("/").content.decode()
        assert 'name="viewport" content="width=device-width, initial-scale=1"' in body

    def test_signed_in_home_redirects_to_chores(self, client):
        roommate = make_roommate(make_household(), "Ada")
        sign_in(client, roommate)
        response = client.get("/")
        assert response.status_code == 302
        assert response.url == "/chores/"


@pytest.mark.django_db
class TestCreateHousehold:
    def test_create_shows_join_code_and_signs_in(self, client):
        response = client.post("/create/", CREATE_PAYLOAD)
        assert response.status_code == 302
        response = client.get(response.url)
        assert response.status_code == 200

        roommate = Roommate.objects.get(display_name="Ada")
        assert client.session["roommate_id"] == roommate.id
        assert roommate.household.join_code in response.content.decode()

    def test_join_code_format_and_uniqueness(self, client):
        from django.test import Client

        client.post("/create/", CREATE_PAYLOAD)
        fresh = Client()
        fresh.post("/create/", {**CREATE_PAYLOAD, "display_name": "Ben"})
        codes = list(Household.objects.values_list("join_code", flat=True))
        assert len(codes) == 2
        assert len(set(codes)) == 2
        assert all(len(code) == 6 for code in codes)

    def test_pin_is_stored_hashed(self, client):
        client.post("/create/", CREATE_PAYLOAD)
        roommate = Roommate.objects.get(display_name="Ada")
        assert roommate.pin != "1234"
        assert roommate.pin.startswith("pbkdf2_")
        assert roommate.check_pin("1234")
        assert not roommate.check_pin("0000")

    def test_invalid_number_shows_error(self, client):
        response = client.post("/create/", {**CREATE_PAYLOAD, "whatsapp_number": "5550001"})
        assert response.status_code == 200
        assert "international format" in response.content.decode()
        assert Roommate.objects.count() == 0

    def test_short_pin_shows_error(self, client):
        response = client.post("/create/", {**CREATE_PAYLOAD, "pin": "12"})
        assert response.status_code == 200
        assert Roommate.objects.count() == 0


@pytest.mark.django_db
class TestJoinHousehold:
    def test_join_creates_roommate_and_signs_in(self, client):
        household = make_household()
        client.post("/join/", {**JOIN_PAYLOAD, "join_code": household.join_code})
        roommate = Roommate.objects.get(display_name="Ben")
        assert roommate.household == household
        assert client.session["roommate_id"] == roommate.id

    def test_wrong_code_shows_visible_error(self, client):
        make_household()
        response = client.post("/join/", {**JOIN_PAYLOAD, "join_code": "ZZZZ99"})
        assert response.status_code == 200
        assert "Unknown join code" in response.content.decode()
        assert "roommate_id" not in client.session

    def test_fifth_roommate_rejected_with_visible_error(self, client):
        household = make_household()
        make_roommate(household, "R1")
        make_roommate(household, "R2", "+15550002")
        make_roommate(household, "R3", "+15550003")
        make_roommate(household, "R4", "+15550004")

        response = client.post(
            "/join/",
            {
                "join_code": household.join_code,
                "display_name": "R5",
                "pin": "5678",
                "whatsapp_number": "+15550005",
            },
        )

        assert response.status_code == 200
        assert "maximum of 4 roommates" in response.content.decode()
        assert household.roommates.count() == MAX_ROOMMATES
        assert "roommate_id" not in client.session

    def test_duplicate_number_with_wrong_pin_rejected(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ada.set_pin("1234")
        ada.save()

        response = client.post(
            "/join/",
            {
                "join_code": household.join_code,
                "display_name": "Impostor",
                "pin": "9999",
                "whatsapp_number": "+15550001",
            },
        )

        assert response.status_code == 200
        assert "Enter its PIN" in response.content.decode()
        assert household.roommates.count() == 1

    def test_duplicate_number_with_correct_pin_restores_identity(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ada.set_pin("1234")
        ada.save()

        response = client.post(
            "/join/",
            {
                "join_code": household.join_code,
                "display_name": "Whatever",
                "pin": "1234",
                "whatsapp_number": "+15550001",
            },
        )

        assert response.status_code == 302
        assert client.session["roommate_id"] == ada.id
        assert household.roommates.count() == 1


@pytest.mark.django_db
class TestProtectedPages:
    def test_signed_out_chore_list_redirects_home(self, client):
        response = client.get("/chores/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_signed_out_join_code_page_redirects_home(self, client):
        response = client.get("/household/code/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_roommate_mixin_redirects_without_session(self, rf, db):
        from django.http import HttpResponse
        from django.views import View

        from chores.views import RoommateRequiredMixin

        class DummyView(RoommateRequiredMixin, View):
            def get(self, request):
                return HttpResponse("ok")

        request = rf.get("/somewhere/")
        request.session = {}
        response = DummyView.as_view()(request)
        assert response.status_code == 302
        assert response.url == "/"

    def test_roommate_mixin_passes_with_session(self, rf, db):
        from django.http import HttpResponse
        from django.views import View

        from chores.views import RoommateRequiredMixin

        roommate = make_roommate(make_household(), "Ada")

        class DummyView(RoommateRequiredMixin, View):
            def get(self, request):
                return HttpResponse(self.roommate.display_name)

        request = rf.get("/somewhere/")
        request.session = {"roommate_id": roommate.id}
        response = DummyView.as_view()(request)
        assert response.content == b"Ada"
