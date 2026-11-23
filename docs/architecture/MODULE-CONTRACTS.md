# Module Contracts

## HTTP contracts

| Capability | Current contract | Compatibility rule |
|---|---|---|
| Accounts | `/api/accounts/` routes from `apps/accounts/urls.py` | Keep login, profile, contacts, privacy, and Google OAuth request/response shapes stable. |
| Chat | `/api/chat/` routes from `apps/chat/urls.py` | Preserve room/message payloads and websocket events. |
| Calls | `/api/calls/` routes from `apps/calls/urls.py` | Preserve call lifecycle and signaling payloads. |
| Status | `/api/status/` routes from `apps/status/urls.py` | Preserve feed, visibility, and status reply behavior. |
| Notifications | `/api/notifications/` routes from `apps/notifications/urls.py` | Preserve push subscription contract. |
| Wallet read-only | `GET /api/wallet/read/?address=...` | New canonical route; authenticated, throttled, public data only. |
| Wallet legacy alias | `GET /api/accounts/wallet/read/?address=...` | Retained as an alias while older clients may use it. |

## Internal public interfaces

- Chat request normalization: `apps.chat.validation.parse_id_list`; `apps.chat.views.parse_id_list` remains importable because the view module imports it into its namespace.
- Status authorization rule: `apps.status.policies.can_view_status`. The old `ContactsStatusAPIView.can_view_status(...)` method delegates to this function for compatibility.
- Wallet UI public export: `frontend/src/features/wallet/index.js` exports `WalletPanel`.
- Wallet HTTP adapter: `frontend/src/features/wallet/api.js` exports `walletApi` and uses the existing shared authenticated API client.

## Authorization and payload rules

Every new API continues through DRF authentication/permission classes already configured. Wallet read has `IsAuthenticated` and its `wallet_read` throttle; it accepts only a validated public account address, verifies Mainnet identity, and never signs or broadcasts. Contact sync keeps explicit consent and member discovery rules. AI continues to require authenticated requests and explicit per-request content consent. Feature switches cannot weaken these requirements.

## Versioning

These are existing same-origin `/api/` contracts with no version prefix. This refactor keeps existing URLs, including a legacy Wallet alias. Any future incompatible contract requires an explicit versioned route and a deprecation window; no payload version is introduced here.
