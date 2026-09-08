import pytest
import requests

from chores import whatsapp
from chores.notifications import notify_roommate

from .test_services import make_chore, make_household, make_roommate
from .test_push import push_calls, vapid_env  # noqa: F401


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def whatsapp_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "test-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")


@pytest.fixture
def post_calls(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(200)

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    return calls


@pytest.mark.django_db
class TestSend_message:
    def test_successful_send_posts_to_graph_api(self, whatsapp_env, post_calls):
        result = whatsapp.send_message("+15550001", '"Bins" is due.')

        assert result is True
        assert len(post_calls) == 1
        call = post_calls[0]
        assert "graph.facebook.com" in call["url"]
        assert "/1234567890/messages" in call["url"]
        assert call["headers"]["Authorization"] == "Bearer test-token"
        assert call["json"]["messaging_product"] == "whatsapp"
        assert call["json"]["to"] == "+15550001"
        assert call["json"]["text"]["body"] == '"Bins" is due.'
        assert call["timeout"] == whatsapp.SEND_TIMEOUT_SECONDS

    def test_non_2xx_response_is_logged_and_returns_false(
        self, whatsapp_env, monkeypatch, caplog
    ):
        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(500)

        monkeypatch.setattr(whatsapp.requests, "post", fake_post)

        with caplog.at_level("WARNING"):
            result = whatsapp.send_message("+15550001", "hello")

        assert result is False
        assert any("failed" in record.message for record in caplog.records)

    def test_connection_error_is_logged_and_returns_false(
        self, whatsapp_env, monkeypatch, caplog
    ):
        def fake_post(url, headers=None, json=None, timeout=None):
            raise requests.ConnectionError("no route to host")

        monkeypatch.setattr(whatsapp.requests, "post", fake_post)

        with caplog.at_level("WARNING"):
            result = whatsapp.send_message("+15550001", "hello")

        assert result is False
        assert any("failed" in record.message for record in caplog.records)

    def test_unset_config_logs_instead_of_sending(self, monkeypatch, post_calls, caplog):
        monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)

        with caplog.at_level("INFO"):
            result = whatsapp.send_message("+15550001", "hello")

        assert result is False
        assert post_calls == []
        assert any("not configured" in record.message for record in caplog.records)


@pytest.mark.django_db
class TestReminderChannel:
    def test_notify_roommate_sends_whatsapp_to_assignee(
        self, vapid_env, whatsapp_env, monkeypatch
    ):
        posted = []

        def fake_post(url, headers=None, json=None, timeout=None):
            posted.append(json)
            return FakeResponse(200)

        monkeypatch.setattr(whatsapp.requests, "post", fake_post)
        household = make_household()
        ada = make_roommate(household, "Ada")

        notify_roommate(ada, "Chore reminder: Bins", '"Bins" is due.')

        assert len(posted) == 1
        assert posted[0]["to"] == "+15550001"
        assert "Bins" in posted[0]["text"]["body"]

    def test_reminder_command_reaches_whatsapp_channel(
        self, vapid_env, whatsapp_env, monkeypatch
    ):
        from datetime import datetime, timezone as dt_timezone

        from django.core.management import call_command

        posted = []

        def fake_post(url, headers=None, json=None, timeout=None):
            posted.append(json)
            return FakeResponse(200)

        monkeypatch.setattr(whatsapp.requests, "post", fake_post)
        clock = datetime(2026, 9, 8, 9, 0, tzinfo=dt_timezone.utc)
        monkeypatch.setattr("django.utils.timezone.now", lambda: clock)

        household = make_household()
        ada = make_roommate(household, "Ada")
        chore = make_chore(household, ada, name="Mop kitchen")
        chore.reminder_time = datetime(2026, 1, 1, 9, 0).time()
        chore.due_at = clock
        chore.save()

        call_command("send_reminders")

        assert len(posted) == 1
        assert posted[0]["to"] == "+15550001"
        assert "Mop kitchen" in posted[0]["text"]["body"]

    def test_no_whatsapp_config_still_sends_web_push(
        self, vapid_env, monkeypatch, push_calls
    ):
        monkeypatch.delenv("WHATSAPP_TOKEN", raising=False)
        monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
        household = make_household()
        ada = make_roommate(household, "Ada")
        from chores.models import PushSubscription

        PushSubscription.objects.create(
            roommate=ada,
            endpoint="https://push.example.com/sub/1",
            p256dh="k",
            auth="a",
        )

        notify_roommate(ada, "Chore reminder", "body")

        assert len(push_calls) == 1
