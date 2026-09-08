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

VALID_ACTIONS = {"explain", "suggest", "create_chore", "create_swap", "edit_chore"}

SYSTEM_PROMPT = """You are the assistant of FairShare Chores, a household chore rotation app.
You help roommates understand fair chore assignment, draft chores or swaps, and edit existing chore settings.
Respond with ONLY a JSON object, no markdown fences, in this exact shape:
{"action": "explain" | "suggest" | "create_chore" | "create_swap" | "edit_chore",
 "message": "short helpful text for explain or suggest, empty string otherwise",
 "payload": {}}
For "create_chore" the payload must be:
{"name": string, "notes": string, "effort": "small"|"medium"|"large",
 "recurrence": "daily"|"weekly"|"monthly"|"custom",
 "custom_count": integer or null, "custom_unit": "hours"|"days"|"weeks"|"months" or null,
 "reminder_time": "HH:MM"}
For "create_swap" the payload must be: {"target_name": string}
For "edit_chore" the payload must contain "chore_name" (the existing chore to change) and
ONLY the fields to change, from: {"reminder_time": "HH:MM", "effort": "small"|"medium"|"large",
 "recurrence": "daily"|"weekly"|"monthly"|"custom",
 "custom_count": integer, "custom_unit": "hours"|"days"|"weeks"|"months"}
Point totals of roommates can never be edited.
Use "explain" when asked why an assignment is fair, "suggest" when asked who should do
something next, "create_chore" to draft a new chore, "create_swap" to draft a swap request,
and "edit_chore" to change an existing chore's settings."""


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


NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}

UNIT_TO_PRESET = {"day": "daily", "week": "weekly", "month": "monthly"}
UNIT_SINGULAR = {"hours": "hours", "days": "days", "weeks": "weeks", "months": "months"}

DRAFT_INTENT = re.compile(
    r"\b(add|create|new|make|schedule)\b|\bevery\b|\bdaily\b|\bweekly\b|\bmonthly\b"
)


def _parse_count(token):
    if token is None:
        return 1
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _parse_reminder_time(lower):
    match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lower)
    if not match:
        return "09:00"
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = match.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return "09:00"


def _match_recurrence(lower):
    match = re.search(
        r"\b(?:every|each)\s+(\d+|[a-z]+)?\s*(hours?|days?|weeks?|months?)\b", lower
    )
    if match:
        count = _parse_count(match.group(1)) or 1
        unit = re.sub(r"s$", "", match.group(2))
        if unit == "hour":
            return "custom", count, "hours"
        if count == 1:
            return UNIT_TO_PRESET[unit], None, None
        return "custom", count, f"{unit}s"
    if re.search(r"\bdaily\b|\bevery day\b", lower):
        return "daily", None, None
    if re.search(r"\bweekly\b|\bevery week\b", lower):
        return "weekly", None, None
    if re.search(r"\bmonthly\b|\bevery month\b", lower):
        return "monthly", None, None
    return None


def _parse_recurrence(lower):
    matched = _match_recurrence(lower)
    if matched is None:
        return "daily", None, None
    return matched


def _parse_chore_draft(text):
    lower = text.lower().strip()
    if re.search(r"\b(large|heavy|big)\b", lower):
        effort = Chore.Effort.LARGE
    elif re.search(r"\b(small|quick|light|easy)\b", lower):
        effort = Chore.Effort.SMALL
    else:
        effort = Chore.Effort.MEDIUM

    reminder_time = _parse_reminder_time(lower)
    recurrence, custom_count, custom_unit = _parse_recurrence(lower)

    name = lower
    name = re.sub(
        r"^(please\s+)?(can you\s+)?(add|create|new|make|schedule|put)(?:\s+"
        r"(a\s+|an\s+|the\s+)?(?:chore\s+)?(?:to\s+|for\s+)?)?",
        "",
        name,
    )
    name = re.sub(r"\b(?:every|each)\s+(\d+|[a-z]+)?\s*(hours?|days?|weeks?|months?)\b", "", name)
    name = re.sub(r"\b(daily|weekly|monthly)\b", "", name)
    name = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(am|pm)?\b", "", name)
    name = re.sub(r"\b(small|medium|large|quick|light|easy|heavy|big)\b", "", name)
    name = re.sub(r"\bchore\b", "", name)
    name = name.strip(" .,!?-")
    if not name:
        return None

    return {
        "name": name[:1].upper() + name[1:],
        "notes": "",
        "effort": effort,
        "recurrence": recurrence,
        "custom_count": custom_count,
        "custom_unit": custom_unit,
        "reminder_time": reminder_time,
    }


def _parse_swap_target(text, household):
    lower = text.lower()
    match = (
        re.search(r"\bswap\b.*?\bwith\s+([a-z\-]+)\b", lower)
        or re.search(r"\bswap\b.*?\bto\s+([a-z\-]+)\b", lower)
    )
    if not match:
        return None, 'Try "swap my chore with <roommate name>".'
    target_name = match.group(1).capitalize()
    for candidate in household.roommates.all():
        if candidate.display_name.lower() == target_name.lower():
            return candidate, None
    available = ", ".join(
        roommate.display_name for roommate in household.roommates.all()
    )
    return None, (
        f'I couldn\'t find a roommate named "{target_name}". '
        f"Household members: {available}."
    )


EDIT_INTENT = re.compile(r"\b(change|set|update|move|edit|reschedule)\b")


def _normalize_time_value(value):
    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", str(value or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def _normalize_edit_fields(fields):
    normalized = {}
    if "reminder_time" in fields:
        reminder = _normalize_time_value(fields.get("reminder_time"))
        if reminder is None:
            return None
        normalized["reminder_time"] = reminder
    if "effort" in fields:
        if fields["effort"] not in Chore.Effort.values:
            return None
        normalized["effort"] = fields["effort"]
    if "recurrence_kind" in fields:
        if fields["recurrence_kind"] not in Chore.RecurrenceKind.values:
            return None
        normalized["recurrence_kind"] = fields["recurrence_kind"]
    if normalized.get("recurrence_kind") == Chore.RecurrenceKind.CUSTOM:
        try:
            count = int(fields.get("custom_count"))
        except (TypeError, ValueError):
            return None
        if count < 1 or fields.get("custom_unit") not in Chore.CustomUnit.values:
            return None
        normalized["custom_count"] = count
        normalized["custom_unit"] = fields["custom_unit"]
    elif "recurrence_kind" in fields:
        normalized["custom_count"] = None
        normalized["custom_unit"] = None
    return normalized


def _match_chore_by_name(text, household):
    lower = text.lower()
    best = None
    best_score = 0
    for chore in household.chores.all():
        tokens = [w for w in re.split(r"\W+", chore.name.lower()) if len(w) > 2]
        if not tokens:
            continue
        score = sum(1 for token in tokens if token in lower)
        if chore.name.lower() in lower:
            score += len(tokens)
        if score > best_score:
            best = chore
            best_score = score
    return best


def _parse_chore_edit(text, household):
    lower = text.lower()
    chore = _match_chore_by_name(text, household)
    if chore is None:
        available = ", ".join(
            chore.name for chore in household.chores.all()
        ) or "no chores yet"
        return None, None, (
            "I couldn't tell which chore you mean. Household chores: " + available + "."
        )

    fields = {}
    reminder_match = re.search(
        r"\b(?:to|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lower
    )
    if reminder_match:
        hour = int(reminder_match.group(1))
        minute = int(reminder_match.group(2) or 0)
        meridiem = reminder_match.group(3)
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            fields["reminder_time"] = f"{hour:02d}:{minute:02d}"

    matched_recurrence = _match_recurrence(lower)
    if matched_recurrence:
        kind, count, unit = matched_recurrence
        fields["recurrence_kind"] = kind
        fields["custom_count"] = count
        fields["custom_unit"] = unit

    for effort, word in (
        (Chore.Effort.LARGE, "large"),
        (Chore.Effort.MEDIUM, "medium"),
        (Chore.Effort.SMALL, "small"),
    ):
        if re.search(rf"\b{word}\b", lower) and word not in chore.name.lower():
            fields["effort"] = effort
            break

    fields = _normalize_edit_fields(fields)
    if not fields:
        return None, None, (
            "I couldn't tell what to change. Try "
            '"change take out rubbish reminder to 8am" or '
            '"set water plants to every 3 days".'
        )
    return chore, fields, None


def _fallback_result(text, household):
    lower = text.lower()

    if "swap" in lower:
        target, error = _parse_swap_target(text, household)
        if target is None:
            return {"ok": False, "action": None, "message": error}
        return {
            "ok": True,
            "action": "create_swap",
            "message": "",
            "draft": {"target_id": target.id, "target_name": target.display_name},
        }

    matched_chore = _match_chore_by_name(text, household)
    wants_edit = bool(EDIT_INTENT.search(lower)) or (
        matched_chore is not None
        and not re.search(r"\b(add|create|new)\b", lower)
    )
    if wants_edit:
        chore, fields, error = _parse_chore_edit(text, household)
        if error:
            return {"ok": False, "action": None, "message": error}
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

    if DRAFT_INTENT.search(lower):
        draft = _parse_chore_draft(text)
        if draft is None:
            return {
                "ok": False,
                "action": None,
                "message": 'I couldn\'t draft a chore from that. '
                'Try "add <chore name> every <N> days/weeks".',
            }
        return {"ok": True, "action": "create_chore", "message": "", "draft": draft}

    if "why" in lower or "explain" in lower:
        totals = _effort_totals(household)
        return {
            "ok": True,
            "action": "explain",
            "message": (
                "Assignments are fair because the chore always goes to the roommate "
                "with the fewest completed effort points. Currently: "
                + "; ".join(_fairness_lines(totals)[:-1])
                + ". "
                + _fairness_lines(totals)[-1]
            ),
            "totals": totals,
        }

    totals = _effort_totals(household)
    return {
        "ok": True,
        "action": "suggest",
        "message": "Next fair assignee: " + _fairness_lines(totals)[-1],
        "totals": totals,
    }


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

    if action == "edit_chore":
        chore_name = str(payload.get("chore_name", "")).strip().lower()
        chore = None
        for candidate in household.chores.all():
            if candidate.name.lower() == chore_name:
                chore = candidate
                break
        if chore is None:
            return _error_result(
                f'I couldn\'t find a chore named "{chore_name}" in this household.'
            )
        fields = {
            key: payload[key]
            for key in ("reminder_time", "effort", "custom_count", "custom_unit")
            if key in payload
        }
        if "recurrence" in payload:
            fields["recurrence_kind"] = payload["recurrence"]
        fields = _normalize_edit_fields(fields)
        if not fields:
            return _error_result(
                "The assistant could not build valid chore changes from that request."
            )
        return {
            "ok": True,
            "action": action,
            "message": "",
            "draft": {
                "chore_id": chore.id,
                "chore_name": chore.name,
                "fields": fields,
            },
        }

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
