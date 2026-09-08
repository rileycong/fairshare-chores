import json
import logging
import os

from pywebpush import WebPushException, webpush

from . import whatsapp

logger = logging.getLogger(__name__)


def _vapid_config():
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    subject = os.environ.get("VAPID_SUBJECT")
    if not private_key or not subject:
        return None
    return {"sub": subject}, private_key


def send_web_push(roommate, title, body):
    config = _vapid_config()
    if config is None:
        logger.info(
            "VAPID keys not configured; skipping web push to %s: %s",
            roommate.display_name,
            title,
        )
        return

    claims, private_key = config
    payload = json.dumps({"title": title, "body": body})

    for subscription in roommate.push_subscriptions.all():
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    },
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=claims,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None) if response else None
            if status in (404, 410):
                logger.info(
                    "push subscription %s is gone; deleting", subscription.id
                )
                subscription.delete()
            else:
                logger.warning(
                    "web push failed for subscription %s: %s", subscription.id, exc
                )


def send_whatsapp(roommate, title, body):
    whatsapp.send_message(roommate.whatsapp_number, f"{title}: {body}")


def notify_roommate(roommate, title, body):
    send_web_push(roommate, title, body)
    send_whatsapp(roommate, title, body)
