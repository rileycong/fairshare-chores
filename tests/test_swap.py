import pytest
from django.utils import timezone

from chores.models import Chore, HistoryRecord, SwapRequest
from chores.services import (
    SwapError,
    request_swap,
    respond_to_swap,
)

from .test_services import make_chore, make_household, make_roommate


def make_swap_trio():
    household = make_household()
    ada = make_roommate(household, "Ada")
    ben = make_roommate(household, "Ben", "+15550002")
    cal = make_roommate(household, "Cal", "+15550003")
    chore = make_chore(household, ada, name="Scrub bathroom")
    return household, ada, ben, cal, chore


@pytest.mark.django_db
class TestRequestSwap:
    def test_assignee_creates_pending_request_and_sets_status(self):
        household, ada, ben, cal, chore = make_swap_trio()

        swap = request_swap(chore, ada, ben)

        assert swap.status == SwapRequest.Status.PENDING
        assert swap.requested_by == ada
        assert swap.target == ben
        chore.refresh_from_db()
        assert chore.status == Chore.Status.SWAP_REQUESTED

    def test_second_request_while_pending_rejected(self):
        household, ada, ben, cal, chore = make_swap_trio()
        request_swap(chore, ada, ben)

        with pytest.raises(SwapError):
            request_swap(chore, ada, cal)

    def test_requester_cannot_swap_with_self(self):
        household, ada, ben, cal, chore = make_swap_trio()

        with pytest.raises(SwapError):
            request_swap(chore, ada, ada)

    def test_non_assignee_cannot_request(self):
        household, ada, ben, cal, chore = make_swap_trio()

        with pytest.raises(SwapError):
            request_swap(chore, ben, cal)

    def test_requester_cannot_request_after_decline_resolved(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        respond_to_swap(swap, ben, accept=False)

        new_swap = request_swap(chore, ada, cal)
        assert new_swap.status == SwapRequest.Status.PENDING


@pytest.mark.django_db
class TestRespondSwap:
    def test_accept_reassigns_to_target_and_restores_assigned(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)

        respond_to_swap(swap, ben, accept=True)

        chore.refresh_from_db()
        assert chore.assignee == ben
        assert chore.status == Chore.Status.ASSIGNED
        assert swap.status == SwapRequest.Status.ACCEPTED
        assert swap.responded_at is not None

    def test_decline_keeps_original_assignee_and_restores_assigned(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)

        respond_to_swap(swap, ben, accept=False)

        chore.refresh_from_db()
        assert chore.assignee == ada
        assert chore.status == Chore.Status.ASSIGNED
        assert swap.status == SwapRequest.Status.DECLINED

    def test_requester_cannot_respond_to_own_request(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)

        with pytest.raises(SwapError):
            respond_to_swap(swap, ada, accept=True)
        assert chore.assignee == ada

    def test_third_roommate_cannot_respond(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)

        with pytest.raises(SwapError):
            respond_to_swap(swap, cal, accept=True)
        assert chore.assignee == ada

    def test_already_answered_request_cannot_change_assignee(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        respond_to_swap(swap, ben, accept=True)

        with pytest.raises(SwapError):
            respond_to_swap(swap, ben, accept=True)
        assert chore.assignee == ben

    def test_accepted_swap_not_reassignable_by_later_decline_attempt(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        respond_to_swap(swap, ben, accept=True)

        with pytest.raises(SwapError):
            respond_to_swap(swap, ben, accept=False)
        assert chore.assignee == ben


@pytest.mark.django_db
class TestSwappedHistoryFlag:
    def test_completion_after_accepted_swap_writes_swapped_true(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        respond_to_swap(swap, ben, accept=True)

        from chores.services import complete_chore

        complete_chore(chore, ben)

        record = HistoryRecord.objects.get()
        assert record.assignee == ben
        assert record.swapped is True

    def test_completion_without_swap_writes_swapped_false(self):
        household, ada, ben, cal, chore = make_swap_trio()

        from chores.services import complete_chore

        complete_chore(chore, ada)

        assert HistoryRecord.objects.get().swapped is False

    def test_completion_after_declined_swap_writes_swapped_false(self):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        respond_to_swap(swap, ben, accept=False)

        from chores.services import complete_chore

        complete_chore(chore, ada)

        assert HistoryRecord.objects.get().swapped is False


@pytest.mark.django_db
class TestSwapViews:
    def sign_in(self, client, roommate):
        session = client.session
        session["roommate_id"] = roommate.id
        session.save()

    def test_assignee_requests_swap_via_ui(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        self.sign_in(client, ada)

        response = client.post(
            f"/chores/{chore.id}/swap/", {"target_id": ben.id}
        )

        assert response.status_code == 302
        assert SwapRequest.objects.filter(chore=chore).count() == 1

    def test_request_with_invalid_target_forbidden(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        self.sign_in(client, ada)

        response = client.post(f"/chores/{chore.id}/swap/", {"target_id": ""})

        assert response.status_code == 403
        assert SwapRequest.objects.count() == 0

    def test_target_sees_pending_request_on_chores_screen(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        self.sign_in(client, ben)

        body = client.get("/chores/").content.decode()

        assert "Swap requests for you" in body
        assert "Scrub bathroom" in body
        assert f'action="/swaps/{swap.id}/accept/"' in body
        assert f'action="/swaps/{swap.id}/decline/"' in body

    def test_requester_sees_no_swap_buttons_on_others_chores(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        request_swap(chore, ada, ben)
        self.sign_in(client, cal)

        body = client.get("/chores/").content.decode()

        assert f'action="/chores/{chore.id}/swap/"' not in body
        assert "Swap requests for you" not in body

    def test_target_accepts_via_ui(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        self.sign_in(client, ben)

        response = client.post(f"/swaps/{swap.id}/accept/")

        assert response.status_code == 302
        chore.refresh_from_db()
        assert chore.assignee == ben
        assert chore.status == Chore.Status.ASSIGNED

    def test_target_declines_via_ui(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        self.sign_in(client, ben)

        response = client.post(f"/swaps/{swap.id}/decline/")

        assert response.status_code == 302
        chore.refresh_from_db()
        assert chore.assignee == ada
        assert chore.status == Chore.Status.ASSIGNED

    def test_non_target_cannot_respond_via_ui(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        self.sign_in(client, cal)

        response = client.post(f"/swaps/{swap.id}/accept/")

        assert response.status_code == 403
        chore.refresh_from_db()
        assert chore.assignee == ada

    def test_swap_target_in_other_household_is_404(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        stranger = make_roommate(make_household("OTHER1"), "Zoe", "+15559999")
        self.sign_in(client, stranger)

        response = client.post(f"/swaps/{swap.id}/accept/")

        assert response.status_code == 404

    def test_get_request_to_respond_does_nothing(self, client):
        household, ada, ben, cal, chore = make_swap_trio()
        swap = request_swap(chore, ada, ben)
        self.sign_in(client, ben)

        response = client.get(f"/swaps/{swap.id}/accept/")

        assert response.status_code == 302
        swap.refresh_from_db()
        assert swap.status == SwapRequest.Status.PENDING
