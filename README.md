# FairShare Chores

A mobile-friendly, installable PWA for 2–4 roommates that fairly rotates household chores by completed effort points, with WhatsApp and web-push reminders and an AI assistant for fair-assignment questions.

## Docs

- Product requirements: [_docs/plan.md](_docs/plan.md)
- How work is organized: [_docs/process.md](_docs/process.md)
- Task template: [_docs/task-template.md](_docs/task-template.md)
- Team roles: [_docs/team/](_docs/team/)
- Backlog: GitHub issues on `rileycong/fairshare-chores` (label `backlog`)

## Setup

```bash
uv sync
cp .env.example .env          # fill in the values you need
uv run python manage.py migrate
uv run python manage.py seed_demo   # optional demo household (join code DEMO01, PIN 1234)
uv run python manage.py runserver
```

## Tests

```bash
uv run pytest            # whole suite
uv run pytest tests/test_home.py   # one file
```

## Reminders

Run every minute (cron/launchd/systemd timer):

```
* * * * * cd /path/to/repo && uv run python manage.py send_reminders
```

## Web push

Generate keys and add them to `.env`:

```bash
uv run python manage.py generate_vapid_keys
```

Env vars: `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` (a `mailto:` address). Roommates enable push on the Settings screen.

## WhatsApp (Meta Cloud API)

1. Create a Meta app with the WhatsApp product and a business phone number.
2. Add a webhook with URL `https://your-domain/webhooks/whatsapp/`, subscribe to the `messages` field, and set a verify token.
3. Put in `.env`: `WHATSAPP_TOKEN` (permanent access token), `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` (the string you entered in the console), `WHATSAPP_APP_SECRET` (app secret, used for signature verification).
4. Roommates reply `done` to the bot to complete their earliest due chore.

## AI assistant

Env vars: `LLM_GATEWAY_API_KEY` (required to enable drafting), `LLM_GATEWAY_BASE_URL` (default `https://api.llmgateway.ai/v1`), `LLM_MODEL` (default `zai/glm-4.5-flash`). Without a key, explain/suggest questions still get a deterministic fairness summary; chore/swap drafts are disabled.

All AI actions that change data require explicit confirmation in the app.
