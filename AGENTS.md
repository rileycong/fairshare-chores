# AGENTS.md

## Commands

- `uv sync` — install dependencies
- `uv run pytest` — run the whole test suite
- `uv run pytest tests/test_home.py` — run one test file
- `uv run python manage.py makemigrations chores` then `uv run python manage.py migrate` — migrations (SQLite, `db.sqlite3` at repo root)

## Rules

- Dependencies are added in `pyproject.toml`. Do not add one without asking.
- Passing tests are the definition of done for each backlog issue.

## State and layout

- Bare Django 4.2 scaffold: project package `config/`, single app `chores/`. All feature work lands in `chores/`; `models.py` is still an empty skeleton and `chores.views.home` is a placeholder for the future welcome/chores screen.
- `plan.md` (repo root) is the product requirements doc; `_docs/plan.md` is the milestone plan. Trust these over the README, whose link to `household-chores-mvp-prd.md` is stale (the file doesn't exist).

## Workflow

- The canonical backlog is GitHub issues on `rileycong/fairshare-chores` (label `backlog`, issues #1–#20), not any file in this repo. Each issue is written to be self-contained — read the issue, do only that task, verify with the test suite.
- `gh` CLI is authenticated as `rileycong`; use it to view/close issues.

## Design constraints (from plan.md — do not violate)

- No email/password accounts: roommate identity is display name + device PIN (hashed) + WhatsApp number, stored in the Django session. Do not build roommate auth on `django.contrib.auth` users (admin stays for debugging only).
- 2–4 roommates per household, one household per device/profile, no admin/manager role.
- Only the current assignee can complete a chore; the next occurrence is scheduled from the original due date, never from completion time. New occurrences go to the lowest completed-effort-point total, ties rotate via the household rotation counter.
- Swaps only through an accepted SwapRequest — no manual reassignment path.
- Every AI action that changes data requires explicit user confirmation before saving; the WhatsApp webhook may only complete chores for the phone number it matches.

## Config

- External integrations (Meta WhatsApp Cloud API, web-push VAPID, LLM Gateway) are configured via env vars (`WHATSAPP_*`, `VAPID_*`, `LLM_GATEWAY_*`). `.env.example` lists them all; `.env.*` is gitignored.
