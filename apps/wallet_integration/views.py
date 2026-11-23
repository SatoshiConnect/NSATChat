"""Messenger's read-only wallet view and ownership-proof bridge.

Public watch addresses are request-scoped. A separate wallet-origin proof flow
stores only an address whose NSAT key signed a short-lived challenge. Neither
path accepts, stores, signs, or broadcasts a transaction.
"""

import base64
import binascii
import hashlib
import json
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode
from django.apps import apps
from django.db import IntegrityError, transaction
from django.utils import timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from rest_framework.exceptions import NotFound
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .models import WalletLink, WalletLinkChallenge


GATEWAY = "https://gateway.satoshicore.org"
INDEXER = "https://satoshicore.org"
MAINNET_ID = "NSAT Mainnet ; October 2026 ; bc3098829fffc717"
ADDRESS_RE = re.compile(r"^G[A-Z2-7]{55}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
LINK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
WALLET_URL = "https://wallet.satoshicore.org/connect/messenger/"


def _decode_wallet_public_key(address):
    """Decode and checksum a canonical Stellar-style NSAT G-address."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        return None
    try:
        encoded = address[1:]
        raw = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 35 or raw[0] != 48:
        return None
    body, checksum = raw[:-2], raw[-2:]
    crc = 0
    for byte in body:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    if checksum != bytes((crc & 0xFF, (crc >> 8) & 0xFF)):
        return None
    return raw[1:33]


def _digest_link_token(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class WalletLinkStartAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def post(self, request):
        token = secrets.token_urlsafe(32)
        now = timezone.now()
        WalletLinkChallenge.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
        issued = int(now.timestamp())
        expires = issued + 300
        account = request.user.public_id or f"member-{request.user.pk}"
        message = (
            "SatoshiCore Messenger wallet link v1\n"
            "Origin: https://chat.satoshicore.org\n"
            f"Account: @{account}\n"
            f"Challenge: {token}\n"
            f"Issued: {issued}\n"
            f"Expires: {expires}"
        )
        WalletLinkChallenge.objects.create(
            user=request.user,
            token_digest=_digest_link_token(token),
            message=message,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        # Keep the one-time capability out of HTTP access logs and referrers.
        wallet_url = f"{WALLET_URL}#{urlencode({'token': token, 'message': message})}"
        return Response({"wallet_url": wallet_url, "expires_at": expires}, status=status.HTTP_201_CREATED)


class WalletLinkConfirmAPIView(APIView):
    # The 256-bit one-use challenge is bound to the authenticated account when
    # created; accepting its signed proof lets installed PWAs return through
    # Safari, whose storage is isolated from the installed app's storage.
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_scope = "wallet_read"

    def post(self, request):
        token = request.data.get("token", "")
        address = str(request.data.get("address", "")).upper()
        signature = request.data.get("signature", "")
        public_key = _decode_wallet_public_key(address)
        if not LINK_TOKEN_RE.fullmatch(str(token)) or not public_key:
            return Response({"code": "invalid_wallet_link"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(signature, str) or len(signature) > 128:
            return Response({"code": "invalid_wallet_link"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            padded = signature + "=" * (-len(signature) % 4)
            signature_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
            if len(signature_bytes) != 64:
                raise ValueError("invalid signature length")
        except (ValueError, UnicodeEncodeError, binascii.Error):
            return Response({"code": "invalid_wallet_link"}, status=status.HTTP_400_BAD_REQUEST)

        digest = _digest_link_token(token)
        try:
            with transaction.atomic():
                challenge = WalletLinkChallenge.objects.select_for_update().get(
                    token_digest=digest,
                    consumed_at__isnull=True,
                    expires_at__gt=timezone.now(),
                )
                Ed25519PublicKey.from_public_bytes(public_key).verify(
                    signature_bytes, challenge.message.encode("utf-8"),
                )
                # Bind to the owner captured by the authenticated start request.
                # The confirmation is intentionally capability-based so an iOS
                # installed PWA can return via Safari without shared auth storage.
                owner = challenge.user
                existing = WalletLink.objects.filter(user=owner).first()
                if existing and existing.address != address:
                    return Response({"code": "wallet_already_linked"}, status=status.HTTP_409_CONFLICT)
                link, _ = WalletLink.objects.get_or_create(user=owner, defaults={"address": address})
                if link.address != address:
                    return Response({"code": "wallet_address_in_use"}, status=status.HTTP_409_CONFLICT)
                challenge.consumed_at = timezone.now()
                challenge.save(update_fields=["consumed_at"])
        except WalletLinkChallenge.DoesNotExist:
            return Response({"code": "wallet_link_expired"}, status=status.HTTP_410_GONE)
        except InvalidSignature:
            return Response({"code": "wallet_signature_invalid"}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response({"code": "wallet_address_in_use"}, status=status.HTTP_409_CONFLICT)
        return Response({"connected": True, "address": address})


class WalletLinkMeAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def get(self, request):
        link = WalletLink.objects.filter(user=request.user).first()
        return Response({"connected": bool(link), "address": link.address if link else ""})

    def delete(self, request):
        WalletLink.objects.filter(user=request.user).delete()
        return Response({"connected": False, "address": ""})


class WalletChatRecipientAPIView(APIView):
    """Expose a verified peer wallet only inside their active private chat."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def get(self, request):
        raw_room_id = request.query_params.get("room_id", "")
        if not str(raw_room_id).isdigit():
            return Response({"code": "invalid_room"}, status=status.HTTP_400_BAD_REQUEST)
        # Resolve chat models through Django's registry to keep the wallet
        # integration module from reaching across the chat app boundary.
        chat_room_model = apps.get_model("chat", "ChatRoom")
        participant_model = apps.get_model("chat", "Participant")
        room = chat_room_model.objects.filter(
            pk=int(raw_room_id),
            room_type="PRIVATE",
            is_active=True,
            participants__user=request.user,
        ).first()
        if not room:
            return Response({"code": "recipient_unavailable"}, status=status.HTTP_404_NOT_FOUND)
        peer = participant_model.objects.filter(room=room).exclude(user=request.user).select_related("user").first()
        if not peer:
            return Response({"code": "recipient_unavailable"}, status=status.HTTP_404_NOT_FOUND)
        link = WalletLink.objects.filter(user=peer.user).only("address").first()
        if not link:
            return Response({"code": "recipient_wallet_not_connected"}, status=status.HTTP_404_NOT_FOUND)
        return Response({"address": link.address, "network": MAINNET_ID})


def _get_json(url):
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "SatoshiCore-Messenger/1.0"})
    with urlopen(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("upstream status")
        raw = response.read(512_001)
    if len(raw) > 512_000:
        raise ValueError("upstream response too large")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unexpected upstream response")
    return payload


def _safe_history(payload):
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("unexpected indexer response")
    safe = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        tx_hash = row.get("hash")
        direction = row.get("direction")
        amount = row.get("amount")
        close_time = row.get("close_time")
        if not isinstance(tx_hash, str) or not HASH_RE.fullmatch(tx_hash):
            continue
        if direction not in {"in", "out", "self"}:
            continue
        if not isinstance(amount, str) or not re.fullmatch(r"\d+", amount):
            continue
        if not isinstance(close_time, int):
            continue
        counterparty = row.get("counterparty")
        if not isinstance(counterparty, str) or not ADDRESS_RE.fullmatch(counterparty):
            counterparty = ""
        safe.append({
            "hash": tx_hash,
            "direction": direction,
            "amount": amount,
            "counterparty": counterparty,
            "kind": str(row.get("kind") or "payment")[:32],
            "close_time": close_time,
            "ledger": row.get("ledger") if isinstance(row.get("ledger"), int) else None,
            "success": row.get("success") is True,
            "result_code": str(row.get("result_code") or "")[:64],
        })
    return safe


class WalletReadAPIView(APIView):
    """Return exact balance and recent indexed history; never enable spending."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not settings.FEATURE_FLAGS["wallet_read_only"]:
            raise NotFound()

    def get(self, request):
        address = str(request.query_params.get("address", "")).strip().upper()
        if not ADDRESS_RE.fullmatch(address):
            return Response({"code": "invalid_address"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            network = _get_json(f"{GATEWAY}/api/v1/network/status")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if network.get("network") != MAINNET_ID or network.get("core") != "ok":
            return Response({"code": "mainnet_unverified"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            account = _get_json(f"{GATEWAY}/api/v1/account?acc={address}")
        except HTTPError as error:
            if error.code == 400:
                return Response({"code": "invalid_address"}, status=status.HTTP_400_BAD_REQUEST)
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        account_status = account.get("status")
        if account_status == "not_found":
            return Response({
                "network": MAINNET_ID,
                "ledger": network.get("ledger") if isinstance(network.get("ledger"), int) else None,
                "address": address,
                "account_status": "not_found",
                "balance": None,
                "history": [],
                "history_status": "available",
                "indexed_head": None,
            })

        balance = account.get("balance128")
        account_id = account.get("id")
        if not isinstance(account_id, str) or account_id.upper() != address or not isinstance(balance, str) or not re.fullmatch(r"\d+", balance):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        history = []
        indexed_head = None
        history_status = "available"
        try:
            indexed = _get_json(f"{INDEXER}/v1/accounts/{address}/transactions?limit=20")
            if indexed.get("account") != address:
                raise ValueError("indexer account mismatch")
            history = _safe_history(indexed)
            indexed_head = indexed.get("indexed_head") if isinstance(indexed.get("indexed_head"), int) else None
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            # Preserve the live balance while reporting that history did not load.
            history_status = "unavailable"

        return Response({
            "network": MAINNET_ID,
            "ledger": network.get("ledger") if isinstance(network.get("ledger"), int) else None,
            "address": address,
            "account_status": "active",
            "balance": balance,
            "history": history,
            "history_status": history_status,
            "indexed_head": indexed_head,
        })
