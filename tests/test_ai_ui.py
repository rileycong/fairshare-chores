import pytest
from django.contrib.messages import get_messages

from chores.models import Chore, HistoryRecord, SwapRequest
from chores.services import request_swap

from .test_services import make_chore, make_household, make_roommate, record_completion


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def make_household_with_history():
    household = make_household()
    ada = make_roommate(household, "Ada")
    ben = make_roommate(household, "Ben", "+15550002")
    chore = make_chore(household, ben, name="Mop")
    record_completion(chore, 3)
    return household, ada, ben


@pytest.fixture
def no_api_key(monkeypatch):
    monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)


def draft_result(action, message="", payload=None):
    return {
        "ok": True,
        "action": action,
        "message": message,
        "draft": payload,
    }


@pytest.mark.django_db
class TestPromptBox:
    def test_prompt_box_renders_on_chores_screen(self, client):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)

        body = client.get("/chores/").content.decode()

        assert 'action="/ai/prompt/"' in body
        assert 'name="text"' in body

    def test_signed_out_cannot_use_prompt(self, client):
        response = client.post("/ai/prompt/", {"text": "why?"})
        assert response.status_code == 302
        assert response.url == "/"

    def test_empty_prompt_redirects(self, client):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)
        response = client.post("/ai/prompt/", {"text": "  "})
        assert response.status_code == 302

    def test_explain_renders_as_text(self, client, no_api_key):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)

        response = client.post("/ai/prompt/", {"text": "why is this fair?"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "fewest completed effort points" in body
        assert HistoryRecord.objects.count() == 1

    def test_ai_failure_renders_readable_message(self, client, no_api_key, monkeypatch):
        household, ada, ben = make_household_with_history()
        monkeypatch.setattr(
            "chores.views.handle_prompt",
            lambda household, roommate, text: {
                "ok": False,
                "action": None,
                "message": "The AI assistant is unavailable right now.",
            },
        )
        sign_in(client, ada)

        response = client.post("/ai/prompt/", {"text": "anything"})

        assert response.status_code == 200
        assert "The AI assistant is unavailable right now." in response.content.decode()

    def test_fallback_draft_renders_confirmation_without_key(
        self, client, no_api_key
    ):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)
        chores_before = Chore.objects.count()

        response = client.post("/ai/prompt/", {"text": "add vacuuming every two weeks"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "Confirm new chore" in body
        assert "Vacuuming" in body
        assert "Will be assigned to" in body
        assert Chore.objects.count() == chores_before

    def test_confirmation_preview_does_not_consume_tie_break(
        self, client, no_api_key, monkeypatch
    ):
        from chores.services import pick_assignee, preview_assignee

        household, ada, ben = make_household_with_history()
        sign_in(client, ada)
        expected = preview_assignee(household)

        client.post("/ai/prompt/", {"text": "add water the plants every day"})

        assert pick_assignee(household) == expected


@pytest.mark.django_db
class TestChoreConfirmation:
    def stub_draft(self, monkeypatch, draft):
        monkeypatch.setattr(
            "chores.views.handle_prompt",
            lambda household, roommate, text: draft_result(
                "create_chore", payload=draft
            ),
        )

    def test_confirmation_renders_parsed_chore_and_saves_nothing_yet(
        self, client, monkeypatch
    ):
        household, ada, ben = make_household_with_history()
        self.stub_draft(
            monkeypatch,
            {
                "name": "Vacuum lounge",
                "notes": "Under the sofa",
                "effort": "large",
                "recurrence": "weekly",
                "custom_count": None,
                "custom_unit": None,
                "reminder_time": "18:00",
            },
        )
        sign_in(client, ada)
        chores_before = Chore.objects.count()

        response = client.post("/ai/prompt/", {"text": "add vacuuming weekly"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "Confirm new chore" in body
        assert "Vacuum lounge" in body
        assert "18:00" in body
        assert 'name="kind" value="chore"' in body
        assert Chore.objects.count() == chores_before

    def test_confirm_creates_chore_via_first_occurrence_path(
        self, client, monkeypatch
    ):
        household, ada, ben = make_household_with_history()
        self.stub_draft(
            monkeypatch,
            {
                "name": "Vacuum lounge",
                "notes": "",
                "effort": "small",
                "recurrence": "daily",
                "custom_count": None,
                "custom_unit": None,
                "reminder_time": "09:00",
            },
        )
        sign_in(client, ada)
        client.post("/ai/prompt/", {"text": "add vacuuming daily"})

        response = client.post(
            "/ai/confirm/",
            {
                "kind": "chore",
                "name": "Vacuum lounge",
                "notes": "",
                "effort": "small",
                "recurrence": "daily",
                "reminder_time": "09:00",
            },
        )

        assert response.status_code == 302
        created = Chore.objects.get(name="Vacuum lounge")
        assert created.household == household
        assert created.assignee == ada
        assert created.status == Chore.Status.ASSIGNED

    def test_cancel_saves_nothing(self, client, monkeypatch):
        household, ada, ben = make_household_with_history()
        self.stub_draft(
            monkeypatch,
            {
                "name": "Vacuum lounge",
                "notes": "",
                "effort": "small",
                "recurrence": "daily",
                "custom_count": None,
                "custom_unit": None,
                "reminder_time": "09:00",
            },
        )
        sign_in(client, ada)
        client.post("/ai/prompt/", {"text": "add vacuuming daily"})
        count_before = Chore.objects.count()

        response = client.get("/chores/")

        assert response.status_code == 200
        assert Chore.objects.count() == count_before

    def test_confirm_with_invalid_payload_rejected(self, client):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)
        count_before = Chore.objects.count()

        response = client.post("/ai/confirm/", {"kind": "chore", "name": ""})

        assert response.status_code == 302
        assert Chore.objects.count() == count_before


@pytest.mark.django_db
class TestSwapConfirmation:
    def stub_swap_draft(self, monkeypatch, target_id, target_name):
        monkeypatch.setattr(
            "chores.views.handle_prompt",
            lambda household, roommate, text: draft_result(
                "create_swap",
                payload={"target_id": target_id, "target_name": target_name},
            ),
        )

    def test_confirmation_renders_target_and_saves_nothing_yet(
        self, client, monkeypatch
    ):
        household, ada, ben = make_household_with_history()
        self.stub_swap_draft(monkeypatch, ben.id, "Ben")
        sign_in(client, ada)

        response = client.post("/ai/prompt/", {"text": "swap my chore with Ben"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "Confirm swap request" in body
        assert "Ben" in body
        assert 'value="swap"' in body
        assert SwapRequest.objects.count() == 0

    def test_confirm_creates_pending_swap_request(self, client, monkeypatch):
        household, ada, ben = make_household_with_history()
        my_chore = make_chore(household, ada, name="Dishes")
        self.stub_swap_draft(monkeypatch, ben.id, "Ben")
        sign_in(client, ada)
        client.post("/ai/prompt/", {"text": "swap with Ben"})

        response = client.post(
            "/ai/confirm/", {"kind": "swap", "target_id": ben.id}
        )

        assert response.status_code == 302
        swap = SwapRequest.objects.get()
        assert swap.chore == my_chore
        assert swap.requested_by == ada
        assert swap.target == ben
        assert swap.status == SwapRequest.Status.PENDING
        my_chore.refresh_from_db()
        assert my_chore.status == Chore.Status.SWAP_REQUESTED

    def test_confirm_without_assigned_chore_is_rejected(self, client, monkeypatch):
        household, ada, ben = make_household_with_history()
        self.stub_swap_draft(monkeypatch, ben.id, "Ben")
        sign_in(client, ada)

        response = client.post(
            "/ai/confirm/", {"kind": "swap", "target_id": ben.id}
        )

        assert response.status_code == 302
        assert SwapRequest.objects.count() == 0

    def test_cancel_swap_saves_nothing(self, client, monkeypatch):
        household, ada, ben = make_household_with_history()
        make_chore(household, ada, name="Dishes")
        self.stub_swap_draft(monkeypatch, ben.id, "Ben")
        sign_in(client, ada)
        client.post("/ai/prompt/", {"text": "swap with Ben"})

        assert client.get("/chores/").status_code == 200
        assert SwapRequest.objects.count() == 0

    def test_unknown_confirmation_kind_rejected(self, client):
        household, ada, ben = make_household_with_history()
        sign_in(client, ada)

        response = client.post("/ai/confirm/", {"kind": "delete_all"})

        assert response.status_code == 302
        assert SwapRequest.objects.count() == 0
        assert Chore.objects.count() == 1
