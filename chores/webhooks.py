import hashlib
import hmac
import json
import logging
import os

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

from .models import Chore, Roommate
from .services import complete_chore

logger = logging.getLogger(__name__)

DONE_WORDS = {"done", "done!", "ok", "ok!"}


def _verify_handshake(request):
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token")
    challenge = request.GET.get("hub.challenge", "")
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and expected and token == expected:
        return HttpResponse(challenge)
    return HttpResponseForbidden("verification failed")


def _signature_valid(request, payload):
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret:
        logger.warning("WHATSAPP_APP_SECRET not configured; rejecting webhook")
        return False
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[len("sha256=") :], digest)


def _extract_message(data):
    try:
        value = data["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        return message.get("from"), message.get("text", {}).get("body")
    except (KeyError, IndexError, TypeError):
        return None, None


def _find_roommate(sender_number):
    if not sender_number:
        return None
    digits = sender_number.lstrip("+")
    return Roommate.objects.filter(
        whatsapp_number__in=[digits, f"+{digits}"]
    ).first()


def _complete_earliest_due(roommate):
    chore = (
        Chore.objects.filter(assignee=roommate)
        .exclude(status=Chore.Status.SWAP_REQUESTED)
        .order_by("due_at")
        .first()
    )
    if chore is None:
        logger.info("no assigned chore for %s; nothing to complete", roommate)
        return
    complete_chore(chore, roommate)
    logger.info("completed %s via WhatsApp for %s", chore.name, roommate)


@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        return _verify_handshake(request)
    if request.method != "POST":
        return HttpResponseForbidden("method not allowed")

    payload = request.body
    if not _signature_valid(request, payload):
        return HttpResponseForbidden("invalid signature")

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("webhook payload was not valid JSON")
        return HttpResponse("ok")

    try:
        sender_number, text = _extract_message(data)
    except Exception:
        logger.exception("failed to parse webhook payload")
        return HttpResponse("ok")

    if not sender_number or not text:
        return HttpResponse("ok")

    roommate = _find_roommate(sender_number)
    if roommate is None:
        logger.info("webhook message from unknown number")
        return HttpResponse("ok")

    if text.strip().lower() in DONE_WORDS:
        try:
            _complete_earliest_due(roommate)
        except Exception:
            logger.exception("failed to complete chore via WhatsApp")

    return HttpResponse("ok")
