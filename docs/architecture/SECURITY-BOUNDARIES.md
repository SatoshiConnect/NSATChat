# Security Boundaries

## Cross-cutting rules

- DRF authentication and per-endpoint authorization remain mandatory; do not add unauthenticated shortcuts to internal capability APIs.
- WebSocket consumers remain responsible for authenticating the connection and checking room/call membership before exposing events.
- Validate identifiers and payloads at their boundary; use domain helpers only after request parsing.
- Keep OAuth/API keys in server-side environment configuration. Do not log tokens, contact contents, private prompts, or wallet secrets.
- Google contact sync accepts explicit consent and minimizes retained data. Contact values must never be forwarded to AI providers.
- Messenger's Wallet API is limited to public data and verified public-address links. The independently hosted Wallet owns keys, signing and broadcasting; the Messenger backend must not collect private keys/seed phrases or sign/broadcast transactions.
- Feature flags only disable optional capabilities; they never bypass identity, object permissions, cryptographic verification, or rate limits.

## Feature switches

Server settings in `config/settings/base.py` read:

| Setting | Environment variable | Default |
|---|---|---:|
| `ai_assistant` | `FEATURE_AI_ASSISTANT` | enabled |
| `ai_image_generation` | `FEATURE_AI_IMAGE_GENERATION` | enabled |
| `google_contacts_sync` | `FEATURE_GOOGLE_CONTACTS_SYNC` | enabled |
| `wallet_read_only` | `FEATURE_WALLET_READ_ONLY` | enabled |
| `experimental` | `FEATURE_EXPERIMENTAL` | disabled |

The frontend Wallet navigation can be hidden at build time with `VITE_FEATURE_WALLET_UI=false`. Server-side checks remain authoritative when the UI is hidden. Flags default to current behavior to avoid an accidental rollout change; production operators must coordinate frontend and backend environment values.

## Wallet boundary

`apps/wallet_integration/views.py` contacts only the public SatoshiCore gateway and indexer, validates the returned chain identity and account, bounds response sizes/history, and responds without persisting the submitted address. Transaction signing/broadcasting remains out of scope and disabled.

## Security review scope

This architecture change is not a complete OWASP ASVS 5.0 Level 2 certification or penetration test. Existing security controls must be reviewed feature-by-feature; this branch does not claim device-level PWA permission coverage, WebRTC abuse testing, or external OAuth verification.
