"""Read-only NSAT Mainnet snapshot for the Messenger wallet screen.

The submitted address is public chain data. It is only held in request memory;
this view never stores it, signs a transaction, or relays a transaction.
"""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


GATEWAY = "https://gateway.satoshicore.org"
INDEXER = "https://satoshicore.org"
MAINNET_ID = "NSAT Mainnet ; October 2026 ; bc3098829fffc717"
ADDRESS_RE = re.compile(r"^G[A-Z2-7]{55}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


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
