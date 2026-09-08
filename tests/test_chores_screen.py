from datetime import timedelta

import pytest
from django.utils import timezone

from chores.models import Chore, HistoryRecord

from .test_services import make_chore, make_household, make_roommate

PAST = timezone.now() - timedelta(days=1)
FUTURE = timezone.now() + timedelta(days=1)


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def make_chores_for_screen():
    household = make_household()
    ada = make_roommate(household, "Ada")
    return household, ada


@pytest.mark.django_db
class TestChoresScreen:
    def test_signed_out_visitor_redirected_home(self, client):
        response = client.get("/chores/")
        assert response.status_code == 302
        assert response.url == "/"

    def test_lists_chore_details_for_own_household(self, client):
        household, ada = make_chores_for_screen()
        make_chore(household, ada, name="Mop kitchen")
        other = make_household("OTHER1")
        make_chore(other, make_roommate(other, "Zoe"), name="Other house chore")

        sign_in(client, ada)
        body = client.get("/chores/").content.decode()

        assert "Mop kitchen" in body
        assert "Ada" in body
        assert "Other house chore" not in body

    def test_shows_notes_and_due_datetime(self, client):
        household, ada = make_chores_for_screen()
        chore = make_chore(household, ada)
        chore.notes = "Use the yellow mop"
        chore.save()

        body = sign_in_and_get(client, ada)
        assert "Use the yellow mop" in body
        assert chore.due_at.strftime("%b") in body

    def test_past_due_chore_displays_overdue_despite_assigned_status(self, client):
        household, ada = make_chores_for_screen()
        chore = make_chore(household, ada, name="Take out rubbish")
        chore.due_at = PAST
        chore.status = Chore.Status.ASSIGNED
        chore.save()

        body = sign_in_and_get(client, ada)

        assert "Overdue" in body
        assert "Take out rubbish" in body
        assert "status-overdue" in body

    def test_swap_requested_chore_shown_in_its_own_group(self, client):
        household, ada = make_chores_for_screen()
        chore = make_chore(household, ada, name="Scrub bathroom")
        chore.status = Chore.Status.SWAP_REQUESTED
        chore.save()

        body = sign_in_and_get(client, ada)

        assert "Swap requested" in body
        assert "status-swap_requested" in body

    def test_future_assigned_chore_shown_as_assigned(self, client):
        household, ada = make_chores_for_screen()
        chore = make_chore(household, ada, name="Vacuum lounge")
        chore.due_at = FUTURE
        chore.save()

        body = sign_in_and_get(client, ada)

        assert "Vacuum lounge" in body
        assert "status-assigned" in body

    def test_refresh_link_present(self, client):
        household, ada = make_chores_for_screen()
        sign_in(client, ada)
        body = client.get("/chores/").content.decode()
        assert 'href="/chores/"' in body

    def test_empty_household_shows_no_chores_message(self, client):
        household, ada = make_chores_for_screen()
        sign_in(client, ada)
        body = client.get("/chores/").content.decode()
        assert "No chores yet" in body


def sign_in_and_get(client, roommate):
    sign_in(client, roommate)
    return client.get("/chores/").content.decode()


@pytest.mark.django_db
class TestCompleteButton:
    def test_assignee_sees_complete_button_on_own_chore_only(self, client):
        household, ada = make_chores_for_screen()
        ben = make_roommate(household, "Ben", "+15550002")
        own = make_chore(household, ada, name="Ada chore")
        other = make_chore(household, ben, name="Ben chore")

        body = sign_in_and_get(client, ada)

        assert f'action="/chores/{own.id}/complete/"' in body
        assert f'action="/chores/{other.id}/complete/"' not in body

    def test_pressing_complete_advances_to_next_occurrence(self, client):
        household, ada = make_chores_for_screen()
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada, name="Water plants")
        chore.recurrence_kind = Chore.RecurrenceKind.WEEKLY
        chore.due_at = FUTURE
        chore.save()

        sign_in(client, ada)
        response = client.post(f"/chores/{chore.id}/complete/")

        assert response.status_code == 302
        assert response.url == "/chores/"
        chore.refresh_from_db()
        assert chore.assignee == ben
        assert HistoryRecord.objects.count() == 1

    def test_non_assignee_post_is_forbidden(self, client):
        household, ada = make_chores_for_screen()
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada, name="Ada chore")

        sign_in(client, ben)
        response = client.post(f"/chores/{chore.id}/complete/")

        assert response.status_code == 403
        assert HistoryRecord.objects.count() == 0
        chore.refresh_from_db()
        assert chore.assignee == ada

    def test_other_household_chore_is_404(self, client):
        household, ada = make_chores_for_screen()
        other = make_household("OTHER1")
        foreign = make_chore(other, make_roommate(other, "Zoe"), name="Foreign chore")

        sign_in(client, ada)
        response = client.post(f"/chores/{foreign.id}/complete/")

        assert response.status_code == 404

    def test_get_request_redirects_without_completing(self, client):
        household, ada = make_chores_for_screen()
        chore = make_chore(household, ada)

        sign_in(client, ada)
        response = client.get(f"/chores/{chore.id}/complete/")

        assert response.status_code == 302
        assert HistoryRecord.objects.count() == 0
