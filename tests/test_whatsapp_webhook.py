import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from chores.models import HistoryRecord

from .test_services import make_chore, make_household, make_roommate

SECRET = "test-app-secret"


def sign(body: bytes) -> str:
    digest = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def message_payload(number="+15550001", text="done") -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": number, "text": {"body": text}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()


def post_message(client, payload: bytes, signature=None):
    kwargs = {}
    if signature is not None:
        kwargs["HTTP_X_Hub_Signature_256"] = signature
    return client.post(
        "/webhooks/whatsapp/",
        data=payload,
        content_type="application/json",
        **kwargs,
    )


@pytest.fixture(autouse=True)
def webhook_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "my-verify-token")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)


@pytest.mark.django_db
class TestVerificationHandshake:
    def test_correct_token_returns_challenge(self, client):
        response = client.get(
            "/webhooks/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "my-verify-token",
                "hub.challenge": "123456",
            },
        )
        assert response.status_code == 200
        assert response.content == b"123456"

    def test_wrong_token_rejected(self, client):
        response = client.get(
            "/webhooks/whatsapp/",
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "123456",
            },
        )
        assert response.status_code == 403


@pytest.mark.django_db
class TestSignatureVerification:
    def test_missing_signature_rejected(self, client):
        household = make_household()
        make_roommate(household, "Ada")

        response = post_message(client, message_payload())

        assert response.status_code == 403
        assert HistoryRecord.objects.count() == 0

    def test_bad_signature_rejected(self, client):
        household = make_household()
        make_roommate(household, "Ada")

        response = post_message(
            client, message_payload(), signature="sha256=" + "0" * 64
        )

        assert response.status_code == 403
        assert HistoryRecord.objects.count() == 0

    def test_non_hex_signature_rejected(self, client):
        household = make_household()
        make_roommate(household, "Ada")

        response = post_message(client, message_payload(), signature="sha256=zzzz")

        assert response.status_code == 403

    def test_no_app_secret_configured_rejects(self, client, monkeypatch):
        monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)

        response = post_message(client, message_payload(), signature=sign(b"anything"))

        assert response.status_code == 403


@pytest.mark.django_db
class TestInboundMessages:
    def test_done_reply_completes_earliest_due_chore(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        early = make_chore(household, ada, name="Sweep floor")
        early.due_at = timezone.now() - timedelta(days=2)
        early.save()
        later = make_chore(household, ada, name="Water plants")
        later.due_at = timezone.now() + timedelta(days=1)
        later.save()
        original_early_due = early.due_at

        response = post_message(
            client, message_payload("+15550001", "done"), signature=sign(message_payload("+15550001", "done"))
        )

        assert response.status_code == 200
        record = HistoryRecord.objects.get()
        assert record.chore.name == "Sweep floor"
        assert record.assignee == ada
        early.refresh_from_db()
        assert early.due_at > original_early_due
        assert early.status == "assigned"

    def test_number_matches_with_or_without_plus(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada)

        response = post_message(
            client, message_payload("15550001", "done"), signature=sign(message_payload("15550001", "done"))
        )

        assert response.status_code == 200
        assert HistoryRecord.objects.count() == 1

    def test_unknown_number_gets_200_no_action(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada)

        payload = message_payload("+19999999", "done")
        response = post_message(client, payload, signature=sign(payload))

        assert response.status_code == 200
        assert HistoryRecord.objects.count() == 0

    def test_sender_cannot_complete_someone_elses_chore(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        adas_chore = make_chore(household, ada, name="Ada chore")

        payload = message_payload("+15550002", "done")
        response = post_message(client, payload, signature=sign(payload))

        assert response.status_code == 200
        assert HistoryRecord.objects.count() == 0
        adas_chore.refresh_from_db()
        assert adas_chore.assignee == ada

    def test_completes_senders_own_chore_not_others(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        make_chore(household, ada, name="Ada chore")
        bens_chore = make_chore(household, ben, name="Ben chore")

        payload = message_payload("+15550002", "done")
        post_message(client, payload, signature=sign(payload))

        record = HistoryRecord.objects.get()
        assert record.chore == bens_chore
        assert record.assignee == ben

    def test_non_done_text_ignored(self, client):
        household = make_household()
        ada = make_roommate(household, "Ada")
        make_chore(household, ada)

        payload = message_payload("+15550001", "what is on my list?")
        post_message(client, payload, signature=sign(payload))

        assert HistoryRecord.objects.count() == 0

    def test_malformed_json_with_valid_signature_gets_200(self, client):
        response = post_message(client, b"not json", signature=sign(b"not json"))
        assert response.status_code == 200

    def test_payload_without_messages_gets_200(self, client):
        payload = json.dumps({"entry": []}).encode()
        response = post_message(client, payload, signature=sign(payload))
        assert response.status_code == 200

    def test_other_http_method_rejected(self, client):
        response = client.delete("/webhooks/whatsapp/")
        assert response.status_code == 403
