# Module Ownership

| Capability | Owns | Does not own |
|---|---|---|
| Accounts | User/profile/contact records, authentication endpoints, OAuth identity, privacy settings, account deletion | Chat room/message state; calls; status feed; Wallet chain access |
| Chat | Chat rooms, membership, messages, receipts, group messaging and assistant API integration | User identity records; WebRTC call state; status privacy policy |
| Calls | Call and call participant records, call lifecycle and signaling | Chat room lifecycle or user credentials |
| Status | Status records, privacy rules, status feed and status reply snapshot/policy | Chat message storage; account identity |
| Notifications | Push subscriptions and delivery formatting/adapters | Ownership of source events or recipient identity |
| Wallet Integration | Read-only gateway/indexer access and Wallet UI | Private keys, seed phrases, signing, broadcasting, wallet engine, Mainnet operations |

## Source ownership and persistence

Current production database ownership follows existing Django models; the new Wallet Integration app defines no models and creates no migration. Cross-app foreign keys in existing models remain where they are. Do not move or rename models without an explicit data-preserving migration plan and production backup.

## Frontend ownership

Feature-owned UI and API code belongs under `frontend/src/features/<capability>/` as each capability is safely migrated. Shared primitives remain under `components/common`, shared transports under `api`/`services`, and the current large component areas stay in place until a focused change can preserve history and regression coverage.
