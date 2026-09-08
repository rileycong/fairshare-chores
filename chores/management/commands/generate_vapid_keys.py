import base64

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.core.management.base import BaseCommand


def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class Command(BaseCommand):
    help = "Generate a VAPID key pair for web push (store in env)"

    def handle(self, *args, **options):
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_bytes = private_key.private_numbers().private_value.to_bytes(32, "big")
        public_bytes = private_key.public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(private_bytes)}")
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(public_bytes)}")
