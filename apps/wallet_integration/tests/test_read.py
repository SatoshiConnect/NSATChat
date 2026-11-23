from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.wallet_integration.views import MAINNET_ID


ADDRESS = "G" + "A" * 55
COUNTERPARTY = "G" + "B" * 55
TX_HASH = "a" * 64


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class WalletReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone_number="+66839930001", password="SafePass123!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("apps.wallet_integration.views._get_json")
    def test_returns_exact_mainnet_balance_and_safe_recent_history(self, get_json):
        get_json.side_effect = [
            {"network": MAINNET_ID, "core": "ok", "ledger": 513832},
            {"id": ADDRESS, "balance128": "900719925474099312345", "status": "ok"},
            {"account": ADDRESS, "indexed_head": 513800, "items": [{
                "hash": TX_HASH, "direction": "in", "amount": "10000000000000001",
                "counterparty": COUNTERPARTY, "kind": "payment", "close_time": 1795415000,
                "ledger": 513800, "success": True, "result_code": "txSUCCESS",
            }]},
        ]

        response = self.client.get("/api/wallet/read/", {"address": ADDRESS})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["balance"], "900719925474099312345")
        self.assertEqual(response.data["network"], MAINNET_ID)
        self.assertEqual(response.data["history"][0]["amount"], "10000000000000001")
        self.assertEqual(response.data["history"][0]["hash"], TX_HASH)
        self.assertEqual(get_json.call_count, 3)

    @patch("apps.wallet_integration.views._get_json")
    def test_rejects_bad_address_before_network_access(self, get_json):
        response = self.client.get("/api/wallet/read/", {"address": "not-an-address"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_address")
        get_json.assert_not_called()

    @patch("apps.wallet_integration.views._get_json")
    def test_fails_closed_when_mainnet_identity_does_not_match(self, get_json):
        get_json.return_value = {"network": "NSAT", "core": "ok", "ledger": 10}
        response = self.client.get("/api/wallet/read/", {"address": ADDRESS})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "mainnet_unverified")
        self.assertEqual(get_json.call_count, 1)

    @patch("apps.wallet_integration.views._get_json")
    def test_does_not_infer_zero_for_address_without_an_account(self, get_json):
        get_json.side_effect = [
            {"network": MAINNET_ID, "core": "ok", "ledger": 513832},
            {"status": "not_found"},
        ]
        response = self.client.get("/api/wallet/read/", {"address": ADDRESS})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["account_status"], "not_found")
        self.assertIsNone(response.data["balance"])
        self.assertEqual(response.data["history"], [])
        self.assertEqual(get_json.call_count, 2)

    @patch("apps.wallet_integration.views._get_json")
    def test_balance_remains_available_when_indexer_is_down(self, get_json):
        get_json.side_effect = [
            {"network": MAINNET_ID, "core": "ok", "ledger": 513832},
            {"id": ADDRESS, "balance128": "42", "status": "ok"},
            OSError("indexer unavailable"),
        ]
        response = self.client.get("/api/wallet/read/", {"address": ADDRESS})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["balance"], "42")
        self.assertEqual(response.data["history_status"], "unavailable")
        self.assertEqual(response.data["history"], [])

    @patch("apps.wallet_integration.views._get_json")
    def test_legacy_read_url_remains_available(self, get_json):
        get_json.side_effect = [
            {"network": MAINNET_ID, "core": "ok", "ledger": 513832},
            {"id": ADDRESS, "balance128": "42", "status": "ok"},
            {"account": ADDRESS, "indexed_head": 513800, "items": []},
        ]

        response = self.client.get("/api/accounts/wallet/read/", {"address": ADDRESS})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["balance"], "42")

    @override_settings(FEATURE_FLAGS={"wallet_read_only": False})
    def test_wallet_read_can_be_disabled_without_disabling_authentication(self):
        response = self.client.get("/api/wallet/read/", {"address": ADDRESS})
        self.assertEqual(response.status_code, 404)
