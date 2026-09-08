import pytest
from django.contrib.messages import get_messages

from chores.models import Chore, HistoryRecord

from .test_services import make_chore, make_household, make_roommate


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def draft_result(chore, fields):
    return {
        "ok": True,
        "action": "edit_chore",
        "message": "",
        "draft": {
            "chore_id": chore.id,
            "chore_name": chore.name,
            "fields": fields,
        },
    }


@pytest.mark.django_db
class TestEditParsing:
    def test_reminder_edit_parsed(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada, name="Take out rubbish")

        from chores.ai import handle_prompt

        result = handle_prompt(
            household, ada, "change take out rubbish reminder to 8am"
        )

        assert result["ok"] is True
        assert result["action"] == "edit_chore"
        assert result["draft"]["fields"]["reminder_time"] == "08:00"

    def test_recurrence_edit_parsed(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada, name="Water plants")

        from chores.ai import handle_prompt

        result = handle_prompt(household, ada, "set water plants to every 3 days")

        assert result["draft"]["fields"]["recurrence_kind"] == "custom"
        assert result["draft"]["fields"]["custom_count"] == 3
        assert result["draft"]["fields"]["custom_unit"] == "days"

    def test_effort_edit_parsed(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada, name="Clean bathroom")

        from chores.ai import handle_prompt

        result = handle_prompt(household, ada, "make clean bathroom large")

        assert result["draft"]["fields"]["effort"] == "large"

    def test_unknown_chore_lists_chores(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada, name="Take out rubbish")

        from chores.ai import handle_prompt

        result = handle_prompt(household, ada, "change mop the deck reminder to 8am")

        assert result["ok"] is False
        assert "Take out rubbish" in result["message"]

    def test_nothing_to_change_returns_hint(self):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada, name="Take out rubbish")

        from chores.ai import handle_prompt

        result = handle_prompt(household, ada, "change take out rubbish")

        assert result["ok"] is False
        assert "couldn't tell what to change" in result["message"]

    def test_llm_edit_chore_action(self, monkeypatch):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        monkeypatch.setenv("LLM_GATEWAY_API_KEY", "test-key")

        import json as jsonlib

        from chores import ai

        content = jsonlib.dumps(
            {
                "action": "edit_chore",
                "message": "",
                "payload": {"chore_name": "Water plants", "reminder_time": "06:30"},
            }
        )

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": content}}]}

        monkeypatch.setattr(ai.requests, "post", lambda *a, **k: FakeResponse())

        result = ai.handle_prompt(household, ada, "move water plants reminder")

        assert result["ok"] is True
        assert result["draft"]["chore_id"] == chore.id
        assert result["draft"]["fields"]["reminder_time"] == "06:30"


@pytest.mark.django_db
class TestEditConfirmation:
    def stub_edit(self, monkeypatch, chore, fields):
        monkeypatch.setattr(
            "chores.views.handle_prompt",
            lambda household, roommate, text: draft_result(chore, fields),
        )

    def test_confirmation_renders_changes_and_saves_nothing_yet(
        self, client, monkeypatch
    ):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        self.stub_edit(monkeypatch, chore, {"reminder_time": "06:30"})
        sign_in(client, ada)
        before = Chore.objects.get(id=chore.id).reminder_time

        response = client.post("/ai/prompt/", {"text": "change water plants reminder"})

        assert response.status_code == 200
        body = response.content.decode()
        assert "Confirm chore update" in body
        assert "06:30" in body
        assert Chore.objects.get(id=chore.id).reminder_time == before

    def test_confirm_applies_reminder_change(self, client, monkeypatch):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        self.stub_edit(monkeypatch, chore, {"reminder_time": "06:30"})
        sign_in(client, ada)

        response = client.post(
            "/ai/confirm/",
            {"kind": "edit_chore", "chore_id": chore.id, "reminder_time": "06:30"},
        )

        assert response.status_code == 302
        chore.refresh_from_db()
        assert str(chore.reminder_time) == "06:30:00"

    def test_confirm_recurrence_change_recomputes_due(self, client, monkeypatch):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        original_due = chore.due_at
        self.stub_edit(
            monkeypatch,
            chore,
            {"recurrence_kind": "custom", "custom_count": 3, "custom_unit": "days"},
        )
        sign_in(client, ada)

        client.post(
            "/ai/confirm/",
            {
                "kind": "edit_chore",
                "chore_id": chore.id,
                "recurrence_kind": "custom",
                "custom_count": 3,
                "custom_unit": "days",
            },
        )

        chore.refresh_from_db()
        assert chore.recurrence_kind == "custom"
        assert chore.custom_count == 3
        assert chore.due_at > original_due

    def test_scores_are_untouched_by_assistant_edits(self, client, monkeypatch):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        self.stub_edit(monkeypatch, chore, {"effort": "large"})
        sign_in(client, ada)
        history_before = HistoryRecord.objects.count()

        client.post(
            "/ai/confirm/",
            {"kind": "edit_chore", "chore_id": chore.id, "effort": "large"},
        )

        chore.refresh_from_db()
        assert chore.effort == "large"
        assert HistoryRecord.objects.count() == history_before

    def test_cancel_saves_nothing(self, client, monkeypatch):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        self.stub_edit(monkeypatch, chore, {"reminder_time": "06:30"})
        sign_in(client, ada)
        client.post("/ai/prompt/", {"text": "change water plants reminder"})

        assert client.get("/chores/").status_code == 200
        chore.refresh_from_db()
        assert str(chore.reminder_time) != "06:30:00"

    def test_confirm_with_invalid_fields_rejected(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Water plants")
        sign_in(client, ada)

        response = client.post(
            "/ai/confirm/",
            {"kind": "edit_chore", "chore_id": chore.id, "reminder_time": "99:99"},
        )

        assert response.status_code == 302
        messages = [m.message for m in get_messages(response.wsgi_request)]
        assert "not valid" in " ".join(messages)
        chore.refresh_from_db()
        assert str(chore.reminder_time) != "09:99"

    def test_edit_missing_chore_rejected(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        sign_in(client, ada)

        response = client.post(
            "/ai/confirm/", {"kind": "edit_chore", "chore_id": "999", "effort": "large"}
        )

        assert response.status_code == 302
