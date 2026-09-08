import json
import logging
import os
import re

import requests
from django.db.models import Sum

from .models import Chore, Roommate

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.llmgateway.ai/v1"
DEFAULT_MODEL = "zai/glm-4.5-flash"
REQUEST_TIMEOUT_SECONDS = 15

VALID_ACTIONS = {"explain", "suggest", "create_chore", "create_swap"}

SYSTEM_PROMPT = """You are the assistant of FairShare Chores, a household chore rotation app.
You help roommates understand fair chore assignment and draft chores or swaps.
Respond with ONLY a JSON object, no markdown fences, in this exact shape:
{"action": "explain" | "suggest" | "create_chore" | "create_swap",
 "message": "short helpful text for explain or suggest, empty string otherwise",
 "payload": {}}
For "create_chore" the payload must be:
{"name": string, "notes": string, "effort": "small"|"medium"|"large",
 "recurrence": "daily"|"weekly"|"monthly"|"custom",
 "custom_count": integer or null, "custom_unit": "hours"|"days"|"weeks"|"months" or null,
 "reminder_time": "HH:MM"}
For "create_swap" the payload must be: {"target_name": string}
Use "explain" when asked why an assignment is fair, "suggest" when asked who should do
something next, "create_chore" to draft a new chore, "create_swap" to draft a swap request."""


def _config():
    api_key = os.environ.get("LLM_GATEWAY_API_KEY")
    if not api_key:
        return None
    return {
        "base_url": os.environ.get("LLM_GATEWAY_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "api_key": api_key,
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL),
    }


def _effort_totals(household):
    totals = []
    for roommate in household.roommates.order_by("id"):
        points = (
            roommate.history_records.aggregate(total=Sum("effort_points"))["total"]
            or 0
        )
        totals.append({"name": roommate.display_name, "points": points})
    return totals


def _fairness_lines(totals):
    if not totals:
        return ["No roommates yet."]
    lowest = min(entry["points"] for entry in totals)
    next_up = ", ".join(
        entry["name"] for entry in totals if entry["points"] == lowest
    )
    lines = [f"{entry['name']}: {entry['points']} points" for entry in totals]
    lines.append(f"Next fair assignee(s): {next_up} (fewest completed points).")
    return lines


def _fallback_result(text, household):
    totals = _effort_totals(household)
    lower = text.lower()
    wants_draft = "add" in lower or "create" in lower or "swap" in lower

    if wants_draft:
        return {
            "ok": False,
            "action": None,
            "message": "Drafting chores and swaps needs an AI API key. "
            "Configure LLM_GATEWAY_API_KEY to use this feature.",
        }

    if "why" in lower or "explain" in lower:
        action = "explain"
        message = (
            "Assignments are fair because the chore always goes to the roommate "
            "with the fewest completed effort points. Currently: "
            + "; ".join(_fairness_lines(totals)[:-1])
            + ". "
            + _fairness_lines(totals)[-1]
        )
    else:
        action = "suggest"
        message = "Next fair assignee: " + _fairness_lines(totals)[-1]

    return {"ok": True, "action": action, "message": message, "totals": totals}


def _strip_fences(content):
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
    if fenced:
        return fenced.group(1)
    return content


def _call_llm(config, household, text):
    user_content = (
        f"Household effort totals: {json.dumps(_effort_totals(household))}. "
        f'Fairness summary: {" ".join(_fairness_lines(_effort_totals(household)))} '
        f'The roommate asking is "{text}".'
    )
    response = requests.post(
        f"{config['base_url']}/chat/completions",
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": config["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(_strip_fences(content))


def _normalize_time(value, default="09:00"):
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", str(value or "").strip())
    if not match:
        return default
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return default


def _normalize_chore_payload(payload):
    name = str(payload.get("name", "")).strip()
    if not name:
        return None
    effort = payload.get("effort")
    if effort not in Chore.Effort.values:
        effort = Chore.Effort.MEDIUM
    recurrence = payload.get("recurrence")
    if recurrence not in Chore.RecurrenceKind.values:
        recurrence = Chore.RecurrenceKind.DAILY
    reminder_time = _normalize_time(payload.get("reminder_time"))

    custom_count = payload.get("custom_count")
    custom_unit = payload.get("custom_unit")
    if recurrence == Chore.RecurrenceKind.CUSTOM:
        try:
            custom_count = int(custom_count)
        except (TypeError, ValueError):
            return None
        if custom_count < 1 or custom_unit not in Chore.CustomUnit.values:
            return None
    else:
        custom_count = None
        custom_unit = None

    return {
        "name": name,
        "notes": str(payload.get("notes", "")).strip(),
        "effort": effort,
        "recurrence": recurrence,
        "custom_count": custom_count,
        "custom_unit": custom_unit,
        "reminder_time": reminder_time,
    }


def _error_result(message):
    return {"ok": False, "action": None, "message": message}


def handle_prompt(household, roommate, text):
    config = _config()
    if config is None:
        return _fallback_result(text, household)

    try:
        result = _call_llm(config, household, text)
        action = result.get("action")
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        logger.exception("AI request failed")
        return _error_result("The AI assistant is unavailable right now.")

    if action not in VALID_ACTIONS:
        return _error_result("The assistant returned an unknown request type.")

    if action in ("explain", "suggest"):
        return {
            "ok": True,
            "action": action,
            "message": result.get("message")
            or " ".join(_fairness_lines(_effort_totals(household))),
        }

    payload = result.get("payload") or {}

    if action == "create_chore":
        draft = _normalize_chore_payload(payload)
        if draft is None:
            return _error_result(
                "The assistant could not build a valid chore from that request."
            )
        return {"ok": True, "action": action, "message": "", "draft": draft}

    target_name = str(payload.get("target_name", "")).strip()
    target = None
    for candidate in household.roommates.all():
        if candidate.display_name.lower() == target_name.lower():
            target = candidate
            break
    if target is None:
        return _error_result(
            f'No roommate named "{target_name}" was found in this household.'
        )
    return {
        "ok": True,
        "action": action,
        "message": "",
        "draft": {"target_id": target.id, "target_name": target.display_name},
    }
