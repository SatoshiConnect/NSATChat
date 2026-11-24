"""Messenger wallet reads, signed-transaction relay, and ownership-proof bridge.

Public watch addresses are request-scoped. A separate wallet-origin proof flow
stores only an address whose NSAT key signed a short-lived challenge. The
transaction relay accepts only a signed XDR envelope; private keys never reach
the server.
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
WALLET_URL = "https://wallet.satoshicore.org/messenger-embed/"


def _decode_wallet_public_key(address):
    """Decode and checksum a canonical Stellar-style NSAT G-address."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        return None
    try:
        # StrKey encodes the version byte as the leading Base32 bits. The
        # visible leading "G" is part of the encoded payload; it must not be
        # stripped before decoding.
        raw = base64.b32decode(address + "=" * (-len(address) % 8))
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


def _wallet_link_message(account, token, issued, expires):
    return (
        "SatoshiCore Messenger wallet link v1\n"
        "Origin: https://chat.satoshicore.org\n"
        f"Account: @{account}\n"
        f"Challenge: {token}\n"
        f"Issued: {issued}\n"
        f"Expires: {expires}"
    )


class WalletLinkStartAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def post(self, request):
        token = secrets.token_urlsafe(32)
        now = timezone.now()
        WalletLinkChallenge.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
        issued = int(now.timestamp())
        issued_at = now.replace(microsecond=0)
        expires = issued + 300
        account = request.user.public_id or f"member-{request.user.pk}"
        if len(account) > 64:
            return Response({"code": "wallet_link_unavailable"}, status=status.HTTP_400_BAD_REQUEST)
        message = _wallet_link_message(account, token, issued, expires)
        WalletLinkChallenge.objects.create(
            user=request.user,
            token_digest=_digest_link_token(token),
            account=account,
            issued_at=issued,
            expires_at=issued_at + timedelta(seconds=300),
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
                expected_message = _wallet_link_message(
                    challenge.account,
                    token,
                    challenge.issued_at,
                    challenge.issued_at + 300,
                )
                Ed25519PublicKey.from_public_bytes(public_key).verify(
                    signature_bytes, expected_message.encode("utf-8"),
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


def _post_json(url, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "SatoshiCore-Messenger/1.0",
        },
    )
    with urlopen(request, timeout=12) as response:
        raw = response.read(65_537)
    if len(raw) > 65_536:
        raise ValueError("upstream response too large")
    result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("unexpected upstream response")
    return result


def _u32(value):
    return int(value).to_bytes(4, "big")


def _encode_wallet_address(public_key):
    """StrKey-encode a raw Ed25519 public key as a public G... address."""
    body = b"\x30" + bytes(public_key)
    crc = 0
    for byte in body:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    tail = bytes((crc & 0xFF, (crc >> 8) & 0xFF))
    return base64.b32encode(body + tail).decode("ascii").rstrip("=")


def _verify_signed_payment_envelope(envelope):
    """Accept only one-signer NSAT V0 native payment/create-account XDR."""
    raw = base64.b64decode(envelope, validate=True)
    if base64.b64encode(raw).decode("ascii") != envelope:
        raise ValueError("non-canonical base64")
    offset = 0

    def take(size):
        nonlocal offset
        if size < 0 or offset + size > len(raw):
            raise ValueError("truncated envelope")
        result = raw[offset:offset + size]
        offset += size
        return result

    def uint32():
        return int.from_bytes(take(4), "big")

    if uint32() != 0:  # TransactionEnvelopeType::ENVELOPE_TYPE_TX_V0
        raise ValueError("unsupported transaction envelope")
    body_start = offset
    source = take(32)
    fee = uint32()
    sequence = int.from_bytes(take(8), "big", signed=True)
    if fee <= 0 or sequence <= 0 or uint32() != 0 or uint32() != 0 or uint32() != 1:
        raise ValueError("unsupported transaction fields")
    if uint32() != 1 or uint32() != 0 or take(32) != source:
        raise ValueError("unsupported operation source")
    operation_type = uint32()
    if operation_type not in {0, 1}:  # CREATE_ACCOUNT / PAYMENT
        raise ValueError("unsupported operation")
    if uint32() != 0:
        raise ValueError("unsupported destination key type")
    destination = take(32)
    if operation_type == 1 and uint32() != 0:  # native asset only
        raise ValueError("unsupported asset")
    amount = int.from_bytes(take(16), "big", signed=True)
    if amount <= 0 or amount > (2**63 - 1) or uint32() != 0:
        raise ValueError("invalid amount or transaction extension")
    tx_body = raw[body_start:offset]
    if uint32() != 1 or take(4) != source[-4:] or uint32() != 64:
        raise ValueError("invalid transaction signature envelope")
    signature = take(64)
    if offset != len(raw):
        raise ValueError("unexpected transaction envelope tail")
    network_hash = hashlib.sha256(MAINNET_ID.encode("utf-8")).digest()
    payload = hashlib.sha256(network_hash + _u32(2) + _u32(0) + tx_body).digest()
    try:
        Ed25519PublicKey.from_public_bytes(source).verify(signature, payload)
    except (ValueError, InvalidSignature) as error:
        raise ValueError("invalid transaction signature") from error
    return {
        "hash": payload.hex(),
        "source": _encode_wallet_address(source),
        "destination": _encode_wallet_address(destination),
        "amount": amount,
        "fee": fee,
        "operation": "create_account" if operation_type == 0 else "payment",
    }


def verify_payment_envelope(envelope):
    """Public entry point shared by wallet send and marketplace settlement."""
    return _verify_signed_payment_envelope(envelope)


def submit_signed_envelope(envelope):
    """Submit one already-verified envelope to the gateway and return its state."""
    if not _verified_mainnet():
        raise ValueError("mainnet unverified")
    result = _post_json(f"{GATEWAY}/api/v1/tx", {"envelope_xdr": envelope})
    result_status = str(result.get("status", "UNKNOWN")).upper()
    if result_status not in {"PENDING", "DUPLICATE", "ERROR", "TRY_AGAIN_LATER", "FILTERED"}:
        result_status = "UNKNOWN"
    return result_status


def confirmation_for_hash(tx_hash, submitted_at):
    """Return the indexer's normalized verdict for a submitted transaction hash."""
    result = _get_json(f"{INDEXER}/v1/confirmations/{tx_hash}?submitted_at={int(submitted_at)}")
    if str(result.get("hash", "")).lower() != tx_hash:
        raise ValueError("confirmation hash mismatch")
    status_value = str(result.get("status", "unknown"))
    if status_value not in {"confirmed", "failed", "pending", "unknown", "not_found"}:
        status_value = "unknown"
    return {
        "status": status_value,
        "success": result.get("success") if isinstance(result.get("success"), bool) else None,
        "result_code": str(result.get("result_code", ""))[:64],
        "ledger": result.get("ledger") if isinstance(result.get("ledger"), int) else None,
    }


def _verified_mainnet():
    network = _get_json(f"{GATEWAY}/api/v1/network/status")
    return network if network.get("network") == MAINNET_ID and network.get("core") == "ok" else None


def _safe_network_failure(error):
    if isinstance(error, HTTPError):
        return Response({"code": "wallet_gateway_rejected"}, status=status.HTTP_502_BAD_GATEWAY)
    return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class WalletPreflightAPIView(APIView):
    """Read fresh source/destination and fee state needed to review a payment."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def get(self, request):
        source = str(request.query_params.get("source", "")).strip().upper()
        destination = str(request.query_params.get("destination", "")).strip().upper()
        if not ADDRESS_RE.fullmatch(source) or not _decode_wallet_public_key(source):
            return Response({"code": "invalid_source_address"}, status=status.HTTP_400_BAD_REQUEST)
        if not ADDRESS_RE.fullmatch(destination) or not _decode_wallet_public_key(destination):
            return Response({"code": "invalid_destination_address"}, status=status.HTTP_400_BAD_REQUEST)
        if source == destination:
            return Response({"code": "self_transfer_not_allowed"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            network = _verified_mainnet()
            if not network:
                return Response({"code": "mainnet_unverified"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            account, recipient, chain = (
                _get_json(f"{GATEWAY}/api/v1/account?acc={source}"),
                _get_json(f"{GATEWAY}/api/v1/account?acc={destination}"),
                _get_json(f"{GATEWAY}/api/v1/chain/info"),
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            return _safe_network_failure(error)

        info = chain.get("info") if isinstance(chain.get("info"), dict) else {}
        ledger = info.get("ledger") if isinstance(info.get("ledger"), dict) else {}
        fee, reserve = ledger.get("baseFee"), ledger.get("baseReserve")
        if info.get("network") != MAINNET_ID or not isinstance(fee, int) or isinstance(fee, bool) or fee <= 0:
            return Response({"code": "mainnet_unverified"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not isinstance(reserve, (int, str)) or not re.fullmatch(r"\d+", str(reserve)):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        account_status = account.get("status")
        if account_status == "not_found":
            return Response({"code": "source_account_not_found"}, status=status.HTTP_409_CONFLICT)
        balance, sequence = account.get("balance128", account.get("balance")), account.get("seqnum")
        source_id = account.get("id")
        if account_status != "ok" or not isinstance(source_id, str) or source_id.upper() != source:
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not isinstance(balance, (str, int)) or not re.fullmatch(r"\d+", str(balance)):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not isinstance(sequence, (str, int)) or not re.fullmatch(r"\d+", str(sequence)):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        destination_exists = recipient.get("status") == "ok"
        recipient_id = recipient.get("id")
        if destination_exists and (not isinstance(recipient_id, str) or recipient_id.upper() != destination):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if recipient.get("status") not in {"ok", "not_found"}:
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            "network": MAINNET_ID,
            "ledger": network.get("ledger") if isinstance(network.get("ledger"), int) else None,
            "source": source,
            "balance": str(balance),
            "sequence": str(sequence),
            "fee": fee,
            "base_reserve": str(reserve),
            "destination": destination,
            "destination_exists": destination_exists,
        })


class WalletSubmitAPIView(APIView):
    """Relay one user-approved signed envelope to the verified NSAT gateway."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_send"

    def post(self, request):
        if not settings.FEATURE_FLAGS.get("wallet_send", False):
            raise NotFound()
        envelope = request.data.get("envelope_xdr") if isinstance(request.data, dict) else None
        if not isinstance(envelope, str) or len(envelope) > 65_536 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", envelope):
            return Response({"code": "invalid_signed_envelope"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            _verify_signed_payment_envelope(envelope)
        except (binascii.Error, ValueError):
            return Response({"code": "invalid_signed_envelope"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            if not _verified_mainnet():
                return Response({"code": "mainnet_unverified"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            result = _post_json(f"{GATEWAY}/api/v1/tx", {"envelope_xdr": envelope})
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            return _safe_network_failure(error)
        result_status = str(result.get("status", "UNKNOWN")).upper()
        if result_status not in {"PENDING", "DUPLICATE", "ERROR", "TRY_AGAIN_LATER", "FILTERED"}:
            result_status = "UNKNOWN"
        return Response({"status": result_status})


class WalletConfirmationAPIView(APIView):
    """Return the indexer's verdict for the exact submitted transaction hash."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "wallet_read"

    def get(self, request, tx_hash):
        submitted_at = str(request.query_params.get("submitted_at", ""))
        if not HASH_RE.fullmatch(tx_hash) or not re.fullmatch(r"\d{1,12}", submitted_at):
            return Response({"code": "invalid_confirmation_query"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            result = _get_json(f"{INDEXER}/v1/confirmations/{tx_hash}?submitted_at={submitted_at}")
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
            return _safe_network_failure(error)
        status_value = str(result.get("status", "unknown"))
        if status_value not in {"confirmed", "failed", "pending", "unknown", "not_found"}:
            status_value = "unknown"
        if str(result.get("hash", "")).lower() != tx_hash:
            return Response({"code": "confirmation_hash_mismatch"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({
            "hash": tx_hash,
            "status": status_value,
            "success": result.get("success") if isinstance(result.get("success"), bool) else None,
            "result_code": str(result.get("result_code", ""))[:64],
            "ledger": result.get("ledger") if isinstance(result.get("ledger"), int) else None,
            "reason": str(result.get("reason", ""))[:128],
        })


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

        # The node-backed account endpoint currently returns an integer
        # ``balance``; newer gateways may expose the exact decimal string as
        # ``balance128``. Normalize either response to a string before JSON so
        # JavaScript never rounds a value above Number.MAX_SAFE_INTEGER.
        balance = account.get("balance128")
        if balance is None:
            balance = account.get("balance")
        account_id = account.get("id")
        if (
            not isinstance(account_id, str)
            or account_id.upper() != address
            or isinstance(balance, bool)
            or not isinstance(balance, (str, int))
            or not re.fullmatch(r"\d+", str(balance))
        ):
            return Response({"code": "wallet_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        balance = str(balance)

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
