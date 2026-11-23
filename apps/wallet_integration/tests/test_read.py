import base64
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.wallet_integration.views import MAINNET_ID


ADDRESS = "G" + "A" * 55
COUNTERPARTY = "G" + "B" * 55
TX_HASH = "a" * 64
VALID_SOURCE = "GAB2CB576PHBBPQ5ODORRZ2LYCMWPZGWGCN2KDK7DXOIMZASKUY3QZ6Q"
VALID_DESTINATION = "GAYJYVAUMI7BY3UBLV5BSKOWYRH5AR6NUFUO4LXGQEJ7SMAUMKAXI7EQ"
SIGNED_PAYMENT_VECTOR = (
    "AAAAAAOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4AAAACgAAAAAAAAAqAAAAAAAAAAAAAAABAAAAAQAAAAADoQe/884Qvh1w3RjnS8CZZ+TWMJulDV8d3IZkElUxuAAAAAEAAAAAMJxUFGI+HG6BXXoZKdbET9BHzaFo7i7mgRP5MBRigXQAAAAAAAAAAAAAAAAAAAAAB1vNFQAAAAAAAAABElUxuAAAAEDX9Qmo/qAWvNRgaXuJ4qLS9O6ggttSVL2xn+TS5yZLvF5dWrdON9M3d/q6nJMUYSorxvXsAoTECJocEKhgDSoO"
)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class WalletReadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone_number="+66839930001", password="SafePass123!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("apps.wallet_integration.views._get_json")
    def test_preflight_returns_only_verified_network_and_account_facts(self, get_json):
        get_json.side_effect = [
            {"network": MAINNET_ID, "core": "ok", "ledger": 513832},
            {"id": VALID_SOURCE, "status": "ok", "balance128": "900000000", "seqnum": 12},
            {"id": VALID_DESTINATION, "status": "ok", "balance128": "10", "seqnum": 1},
            {"info": {"network": MAINNET_ID, "ledger": {"baseFee": 10, "baseReserve": 100000000}}},
        ]
        response = self.client.get("/api/wallet/preflight/", {"source": VALID_SOURCE, "destination": VALID_DESTINATION})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["balance"], "900000000")
        self.assertEqual(response.data["sequence"], "12")
        self.assertEqual(response.data["fee"], 10)
        self.assertEqual(response.data["base_reserve"], "100000000")
        self.assertTrue(response.data["destination_exists"])

    @patch("apps.wallet_integration.views._get_json")
    def test_preflight_refuses_unverified_mainnet_before_account_reads(self, get_json):
        get_json.return_value = {"network": "NSAT Devnet", "core": "ok"}
        response = self.client.get("/api/wallet/preflight/", {"source": VALID_SOURCE, "destination": VALID_DESTINATION})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "mainnet_unverified")
        self.assertEqual(get_json.call_count, 1)

    @patch("apps.wallet_integration.views._post_json")
    @patch("apps.wallet_integration.views._verified_mainnet")
    def test_submit_relays_only_signed_envelope_without_returning_it(self, verified, post_json):
        verified.return_value = {"network": MAINNET_ID, "core": "ok"}
        post_json.return_value = {"status": "PENDING", "envelope_xdr": "must-not-be-returned"}
        envelope = SIGNED_PAYMENT_VECTOR
        response = self.client.post("/api/wallet/submit/", {"envelope_xdr": envelope}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"status": "PENDING"})
        post_json.assert_called_once_with("https://gateway.satoshicore.org/api/v1/tx", {"envelope_xdr": envelope})

    @patch("apps.wallet_integration.views._post_json")
    @patch("apps.wallet_integration.views._verified_mainnet")
    def test_submit_rejects_invalid_signatures_before_gateway_access(self, verified, post_json):
        verified.return_value = {"network": MAINNET_ID, "core": "ok"}
        damaged = bytearray(base64.b64decode(SIGNED_PAYMENT_VECTOR))
        damaged[-1] ^= 1
        response = self.client.post("/api/wallet/submit/", {"envelope_xdr": base64.b64encode(damaged).decode("ascii")}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_signed_envelope")
        post_json.assert_not_called()

    @override_settings(FEATURE_FLAGS={"wallet_send": False})
    def test_submit_can_be_disabled_by_feature_flag(self):
        response = self.client.post("/api/wallet/submit/", {"envelope_xdr": "aGVsbG8="}, format="json")
        self.assertEqual(response.status_code, 404)

    @patch("apps.wallet_integration.views._get_json")
    def test_confirmation_verifies_the_exact_hash_and_exposes_safe_fields(self, get_json):
        get_json.return_value = {"hash": TX_HASH, "status": "confirmed", "success": True, "ledger": 513900, "result_code": "txSUCCESS", "secret": "not exposed"}
        response = self.client.get(f"/api/wallet/confirmation/{TX_HASH}/", {"submitted_at": "1795415000"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["hash"], TX_HASH)
        self.assertTrue(response.data["success"])
        self.assertNotIn("secret", response.data)

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
