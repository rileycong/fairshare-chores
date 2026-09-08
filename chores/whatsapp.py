import logging
import os

import requests

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"
SEND_TIMEOUT_SECONDS = 10


def _config():
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if not token or not phone_number_id:
        return None
    return token, phone_number_id


def send_message(phone_number, body):
    config = _config()
    if config is None:
        logger.info(
            "WhatsApp not configured; skipping message to %s", phone_number
        )
        return False

    token, phone_number_id = config
    try:
        response = requests.post(
            GRAPH_API_URL.format(phone_number_id=phone_number_id),
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": body},
            },
            timeout=SEND_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.warning("WhatsApp send to %s failed: %s", phone_number, exc)
        return False
