# Refactor Changelog

## Modular architecture slice

- Added model-free Django app `apps.wallet_integration` to own the read-only Wallet API.
- Mounted canonical `/api/wallet/read/` and retained `/api/accounts/wallet/read/` as a legacy alias.
- Moved Wallet panel and API adapter to `frontend/src/features/wallet/`; kept existing shared API client, UI primitives, stylesheet, and Wallet read-only behavior.
- Moved chat ID parsing to `apps/chat/validation.py`; the view import remains available to existing callers.
- Extracted status visibility into `apps/status/policies.py`; kept the prior view method as a delegating compatibility wrapper and removed the service-to-view dependency.
- Removed unused cross-app imports from account admin and deferred an account-to-chat import to the view method that needs it.
- Added optional feature switches for AI, image generation, Google Contacts sync, and Wallet read-only endpoint; these default to current behavior. Wallet UI can be hidden at frontend build time.
- Added static architecture boundary tests and this source-based architecture documentation.

## Explicitly unchanged

No models, migrations, external service protocol, WebSocket payload, call engine, PWA setup, authentication flow, or Mainnet transaction behavior was changed.
