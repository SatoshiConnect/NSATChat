# NSAT Messenger Architecture

## Current shape

NSAT Messenger is a Django/Channels and React modular monolith. Django owns the authenticated HTTP API, persistence, WebSocket consumers, and call signaling. The React application owns presentation and client state. The deployment remains one application with shared infrastructure; no service split or replacement engine is introduced by this change.

The installed Django capabilities are `accounts`, `chat`, `calls`, `status`, `notifications`, and the new model-free `wallet_integration` app. Their `AppConfig`/installation list is in `config/settings/base.py`. Product APIs are mounted in `config/urls.py` at `/api/accounts/`, `/api/chat/`, `/api/calls/`, `/api/status/`, `/api/notifications/`, and `/api/wallet/`.

The React source is currently organized mostly by component role (`components/chat-list`, `components/conversation`, `components/calls`, `components/contacts`, `components/assistant`, and `components/profile`). Wallet is the first complete feature slice under `src/features/wallet/`, with a public export, its own API adapter, and its panel. Existing shared API transport remains in `src/api/client.js`.

## Capability responsibilities

- **Accounts**: users, profiles, login/registration, contacts, privacy, Google Contacts matching, and account lifecycle. Source: `apps/accounts/models/`, `views.py`, `google_contacts.py`, `privacy.py`, `deletion.py`.
- **Chat**: rooms, participants, messages, receipts, group features, message APIs, WebSocket chat behavior, and SatoshiCore AI endpoint. Source: `apps/chat/models/`, `views.py`, `consumers.py`, `assistant.py`, `features.py`.
- **Calls**: call state, call participants, call APIs, consumers, and signaling lifecycle. Source: `apps/calls/models/`, `views.py`, `consumers.py`, `lifecycle.py`, `group.py`.
- **Status**: status records, visibility/privacy policy, feed, reactions, and replies. Source: `apps/status/models/`, `views.py`, `policies.py`, `replies.py`.
- **Notifications**: push subscriptions and delivery adapters. Source: `apps/notifications/models.py`, `push.py`, `consumers.py`.
- **Wallet Integration**: authenticated public Mainnet reads and verified address linking; the Wallet screen embeds the independently hosted SatoshiCore Wallet so signing and Mainnet operations stay on the Wallet origin. Messenger stores no wallet keys and has no Wallet models. Source: `apps/wallet_integration/views.py` and `frontend/src/features/wallet/`.

## Refactor boundaries

This refactor does not move database models, alter migrations, replace chat/call engines, or introduce a plugin framework. It extracts the status visibility rule from its HTTP view, centralizes chat ID parsing outside views, and moves the read-only Wallet endpoint and UI into capability-owned modules. Cross-app model relations and selected direct service calls remain because they are part of current behavior; see `MODULE-DEPENDENCIES.md` and `MIGRATION-PLAN.md`.

## Feature switches

Optional server capabilities use `FEATURE_FLAGS` in `config/settings/base.py`; environment names are documented in `SECURITY-BOUNDARIES.md`. Feature flags only gate optional AI, contact-sync, or read-only Wallet capabilities. They do not bypass authentication, authorization, cryptographic verification, or call/chat security. Wallet UI can separately be hidden at build time with `VITE_FEATURE_WALLET_UI=false`.

## Runtime layers

HTTP routes call DRF views, which use serializers, domain helpers, and Django models. WebSocket routes are configured in `config/routing.py` and consumers authorize using persisted membership/ownership. React features call the shared authenticated API client and existing realtime service. No database or WebSocket protocol changes are part of this refactor.
