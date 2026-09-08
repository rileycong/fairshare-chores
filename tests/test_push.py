import json

import pytest
from django.core.management import call_command
from django.utils import timezone

from chores.models import Chore, PushSubscription
from chores.notifications import notify_roommate

from .test_services import make_chore, make_household, make_roommate


@pytest.fixture
def vapid_env(monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHr8")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")


@pytest.fixture
def push_calls(monkeypatch):
    calls = []

    def fake_webpush(**kwargs):
        calls.append(kwargs)
        endpoint = kwargs["subscription_info"]["endpoint"]
        if endpoint.endswith("dead"):
            raise __import__("pywebpush").WebPushException("push failed")

    monkeypatch.setattr("chores.notifications.webpush", fake_webpush)
    return calls


def make_gone_exception(monkeypatch):
    class FakeWebPushException(Exception):
        def __init__(self, status_code):
            super().__init__("push failed")
            self.response = type("R", (), {"status_code": status_code})()

    monkeypatch.setattr("chores.notifications.WebPushException", FakeWebPushException)
    return FakeWebPushException


def sign_in(client, roommate):
    session = client.session
    session["roommate_id"] = roommate.id
    session.save()


def subscription_payload(endpoint="https://push.example.com/sub/1", p256dh="key-a"):
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": p256dh, "auth": "auth-a"},
    }


@pytest.mark.django_db
class TestGenerateVapidKeys:
    def test_command_prints_key_pair(self, capsys):
        call_command("generate_vapid_keys")
        out = capsys.readouterr().out
        assert "VAPID_PRIVATE_KEY=" in out
        assert "VAPID_PUBLIC_KEY=" in out

        import base64

        public = out.strip().splitlines()[1].split("=", 1)[1]
        padded = public + "=" * (-len(public) % 4)
        raw = base64.urlsafe_b64decode(padded)
        assert len(raw) == 65 and raw[0] == 4


@pytest.mark.django_db
class TestPushSubscribe:
    def test_stores_subscription_for_signed_in_roommate(self, client):
        roommate = make_roommate(make_household(), "Ada")
        sign_in(client, roommate)

        response = client.post(
            "/push/subscribe/",
            data=json.dumps(subscription_payload()),
            content_type="application/json",
        )

        assert response.status_code == 200
        sub = PushSubscription.objects.get()
        assert sub.roommate == roommate
        assert sub.endpoint == "https://push.example.com/sub/1"
        assert sub.p256dh == "key-a"
        assert sub.auth == "auth-a"

    def test_duplicate_endpoint_updates_instead_of_failing(self, client):
        roommate = make_roommate(make_household(), "Ada")
        sign_in(client, roommate)

        client.post(
            "/push/subscribe/",
            data=json.dumps(subscription_payload()),
            content_type="application/json",
        )
        response = client.post(
            "/push/subscribe/",
            data=json.dumps(subscription_payload(p256dh="key-b")),
            content_type="application/json",
        )

        assert response.status_code == 200
        assert PushSubscription.objects.count() == 1
        assert PushSubscription.objects.get().p256dh == "key-b"

    def test_invalid_payload_is_400(self, client):
        roommate = make_roommate(make_household(), "Ada")
        sign_in(client, roommate)

        response = client.post(
            "/push/subscribe/", data="not json", content_type="application/json"
        )

        assert response.status_code == 400
        assert PushSubscription.objects.count() == 0

    def test_signed_out_is_403(self, client):
        response = client.post(
            "/push/subscribe/",
            data=json.dumps(subscription_payload()),
            content_type="application/json",
        )
        assert response.status_code == 403

    def test_settings_screen_wires_enable_toggle(self, client, monkeypatch):
        monkeypatch.setenv("VAPID_PUBLIC_KEY", "BPubKey123")
        roommate = make_roommate(make_household(), "Ada")
        sign_in(client, roommate)

        body = client.get("/settings/").content.decode()

        assert 'id="enable-push"' in body
        assert 'data-vapid-public-key="BPubKey123"' in body
        assert "/static/js/push.js" in body
        assert "Notification.requestPermission" not in body


@pytest.mark.django_db
class TestNotifyRoommate:
    def test_sends_to_all_subscriptions(self, vapid_env, push_calls):
        household = make_household()
        roommate = make_roommate(household, "Ada")
        PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/sub/1",
            p256dh="k1",
            auth="a1",
        )
        PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/sub/2",
            p256dh="k2",
            auth="a2",
        )

        notify_roommate(roommate, "Chore due", "Take out rubbish is due")

        assert len(push_calls) == 2
        endpoints = {call["subscription_info"]["endpoint"] for call in push_calls}
        assert endpoints == {
            "https://push.example.com/sub/1",
            "https://push.example.com/sub/2",
        }
        import json as jsonlib

        assert jsonlib.loads(push_calls[0]["data"]) == {
            "title": "Chore due",
            "body": "Take out rubbish is due",
        }
        assert "mailto:ops@example.com" in push_calls[0]["vapid_claims"]["sub"]

    def test_only_targets_given_roommate(self, vapid_env, push_calls):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        PushSubscription.objects.create(
            roommate=ada, endpoint="https://push.example.com/ada", p256dh="k", auth="a"
        )
        PushSubscription.objects.create(
            roommate=ben, endpoint="https://push.example.com/ben", p256dh="k", auth="a"
        )

        notify_roommate(ada, "Chore due", "body")

        assert len(push_calls) == 1
        assert push_calls[0]["subscription_info"]["endpoint"] == (
            "https://push.example.com/ada"
        )

    def test_without_vapid_config_logs_instead_of_raising(
        self, monkeypatch, push_calls
    ):
        monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
        monkeypatch.delenv("VAPID_SUBJECT", raising=False)
        household = make_household()
        roommate = make_roommate(household, "Ada")
        PushSubscription.objects.create(
            roommate=roommate, endpoint="https://push.example.com/sub", p256dh="k", auth="a"
        )

        notify_roommate(roommate, "Chore due", "body")

        assert push_calls == []

    def test_failed_push_does_not_block_other_subscriptions(
        self, vapid_env, push_calls
    ):
        household = make_household()
        roommate = make_roommate(household, "Ada")
        PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/dead",
            p256dh="k",
            auth="a",
        )
        PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/alive",
            p256dh="k",
            auth="a",
        )

        notify_roommate(roommate, "Chore due", "body")

        endpoints = [call["subscription_info"]["endpoint"] for call in push_calls]
        assert "https://push.example.com/alive" in endpoints

    def test_gone_subscription_is_deleted(self, vapid_env, monkeypatch):
        FakeWebPushException = make_gone_exception(monkeypatch)

        def fake_webpush(**kwargs):
            if kwargs["subscription_info"]["endpoint"].endswith("gone"):
                raise FakeWebPushException(410)

        monkeypatch.setattr("chores.notifications.webpush", fake_webpush)

        household = make_household()
        roommate = make_roommate(household, "Ada")
        gone = PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/gone",
            p256dh="k",
            auth="a",
        )
        alive = PushSubscription.objects.create(
            roommate=roommate,
            endpoint="https://push.example.com/alive",
            p256dh="k",
            auth="a",
        )

        notify_roommate(roommate, "Chore due", "body")

        assert not PushSubscription.objects.filter(id=gone.id).exists()
        assert PushSubscription.objects.filter(id=alive.id).exists()
