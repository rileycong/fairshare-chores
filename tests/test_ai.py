import json

import pytest
import requests

from chores import ai
from chores.models import Chore, SwapRequest

from .test_services import make_chore, make_household, make_roommate, record_completion

API_ENV = {
    "LLM_GATEWAY_BASE_URL": "https://llm.test/v1",
    "LLM_GATEWAY_API_KEY": "test-key",
    "LLM_MODEL": "test-model",
}


@pytest.fixture
def api_env(monkeypatch):
    for key, value in API_ENV.items():
        monkeypatch.setenv(key, value)


class FakeLLMResponse:
    def __init__(self, content, status_ok=True):
        self._content = content
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("HTTP 500")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def llm_content(action, message="", payload=None):
    return json.dumps({"action": action, "message": message, "payload": payload or {}})


def post_stub(monkeypatch, contents):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        content = contents.pop(0) if isinstance(contents, list) else contents
        return FakeLLMResponse(content)

    monkeypatch.setattr(ai.requests, "post", fake_post)
    return calls


def make_household_with_history():
    household = make_household()
    ada = make_roommate(household, "Ada")
    ben = make_roommate(household, "Ben", "+15550002")
    chore = make_chore(household, ben, name="Mop")
    record_completion(chore, 3)
    return household, ada, ben


@pytest.mark.django_db
class TestNoKeyFallback:
    def test_explain_falls_back_to_deterministic_summary(self, monkeypatch):
        monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)
        household, ada, ben = make_household_with_history()

        result = ai.handle_prompt(household, ada, "Why is this fair?")

        assert result["ok"] is True
        assert result["action"] == "explain"
        assert "fewest completed effort points" in result["message"]
        assert "Ben: 3 points" in result["message"]
        assert "Ada: 0 points" in result["message"]

    def test_suggest_falls_back_to_lowest_total(self, monkeypatch):
        monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)
        household, ada, ben = make_household_with_history()

        result = ai.handle_prompt(household, ada, "Who should do the next chore?")

        assert result["ok"] is True
        assert result["action"] == "suggest"
        assert "Ada" in result["message"]

    def test_draft_requests_report_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("LLM_GATEWAY_API_KEY", raising=False)
        household, ada, ben = make_household_with_history()
        chores_before = Chore.objects.count()

        result = ai.handle_prompt(
            household, ada, "add vacuuming every two weeks"
        )

        assert result["ok"] is False
        assert "API key" in result["message"]
        assert Chore.objects.count() == chores_before


@pytest.mark.django_db
class TestLLMActions:
    def test_explain_returns_model_message(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        calls = post_stub(
            monkeypatch, llm_content("explain", "Ben did more this week.")
        )

        result = ai.handle_prompt(household, ada, "why ben?")

        assert result == {
            "ok": True,
            "action": "explain",
            "message": "Ben did more this week.",
        }
        assert calls[0]["url"].startswith("https://llm.test/v1/")
        assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
        assert calls[0]["json"]["model"] == "test-model"
        sent = calls[0]["json"]["messages"]
        assert sent[0]["role"] == "system"
        assert '"action": "explain"' in sent[0]["content"].replace(" ", " ") or (
            "explain" in sent[0]["content"]
        )
        assert "Ada" in sent[1]["content"]

    def test_suggest_returns_model_message(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(monkeypatch, llm_content("suggest", "Ada should take it."))

        result = ai.handle_prompt(household, ada, "who is next?")

        assert result["ok"] is True
        assert result["action"] == "suggest"
        assert result["message"] == "Ada should take it."

    def test_create_chore_returns_normalized_draft_without_saving(
        self, api_env, monkeypatch
    ):
        household, ada, ben = make_household_with_history()
        payload = {
            "name": "Vacuum lounge",
            "notes": "Under the sofa too",
            "effort": "large",
            "recurrence": "custom",
            "custom_count": 2,
            "custom_unit": "weeks",
            "reminder_time": "18:5",
        }
        post_stub(monkeypatch, llm_content("create_chore", payload=payload))

        result = ai.handle_prompt(household, ada, "add vacuuming every two weeks")

        assert result["ok"] is True
        assert result["action"] == "create_chore"
        assert result["draft"] == {
            "name": "Vacuum lounge",
            "notes": "Under the sofa too",
            "effort": "large",
            "recurrence": "custom",
            "custom_count": 2,
            "custom_unit": "weeks",
            "reminder_time": "18:05",
        }
        assert Chore.objects.count() == 1

    def test_create_chore_with_invalid_payload_is_safe_error(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(monkeypatch, llm_content("create_chore", payload={"name": ""}))

        result = ai.handle_prompt(household, ada, "add a chore")

        assert result["ok"] is False
        assert Chore.objects.count() == 1

    def test_create_swap_matches_target_without_saving(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(
            monkeypatch, llm_content("create_swap", payload={"target_name": "Ben"})
        )

        result = ai.handle_prompt(household, ada, "swap my chore with Ben this week")

        assert result["ok"] is True
        assert result["action"] == "create_swap"
        assert result["draft"] == {"target_id": ben.id, "target_name": "Ben"}
        assert SwapRequest.objects.count() == 0

    def test_create_swap_with_unknown_target_is_safe_error(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(
            monkeypatch, llm_content("create_swap", payload={"target_name": "Zoe"})
        )

        result = ai.handle_prompt(household, ada, "swap with Zoe")

        assert result["ok"] is False
        assert "No roommate named" in result["message"]
        assert SwapRequest.objects.count() == 0


@pytest.mark.django_db
class TestMalformedOutput:
    def test_invalid_json_returns_safe_error(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(monkeypatch, "this is not json at all")

        result = ai.handle_prompt(household, ada, "anything")

        assert result["ok"] is False
        assert result["message"] == "The AI assistant is unavailable right now."

    def test_unknown_action_returns_safe_error(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        post_stub(monkeypatch, llm_content("delete_everything"))

        result = ai.handle_prompt(household, ada, "anything")

        assert result["ok"] is False
        assert "unknown request type" in result["message"]

    def test_fenced_json_is_parsed(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        fenced = "```json\n" + llm_content("explain", "Because points.") + "\n```"
        post_stub(monkeypatch, fenced)

        result = ai.handle_prompt(household, ada, "why?")

        assert result["ok"] is True
        assert result["message"] == "Because points."

    def test_http_failure_returns_safe_error(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()

        def fake_post(url, headers=None, json=None, timeout=None):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(ai.requests, "post", fake_post)

        result = ai.handle_prompt(household, ada, "anything")

        assert result["ok"] is False
        assert result["message"] == "The AI assistant is unavailable right now."

    def test_request_has_timeout(self, api_env, monkeypatch):
        household, ada, ben = make_household_with_history()
        calls = post_stub(monkeypatch, llm_content("explain", "ok"))

        ai.handle_prompt(household, ada, "why?")

        assert calls[0]["timeout"] == ai.REQUEST_TIMEOUT_SECONDS
