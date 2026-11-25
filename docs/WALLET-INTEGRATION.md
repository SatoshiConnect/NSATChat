# NSATChat native wallet

The Messenger Wallet is a first-party React feature rendered inside NSATChat. It does not embed or redirect to `wallet.satoshicore.org`.

## Capabilities

- Create or restore a non-custodial account in the browser. The S… recovery key is encrypted at rest on this device with PBKDF2-SHA256 and AES-256-GCM. The backend never receives it.
- Read balance and recent activity through authenticated `/api/wallet/read/`.
- Open a zero-balance wallet on Mainnet at zero fee when the live Core policy allows self-open. The owner must unlock and sign with that wallet's own key; NSATChat verifies the live policy and exact transaction before relaying it.
- Generate a receive QR locally and create/share payment requests in one-to-one chats.
- Prepare a payment from fresh authenticated `/api/wallet/preflight/` data. The browser verifies the exact Mainnet identity, recipient checksum, exact integer amount, live 10 NSAT fee policy, account sequence, balance, and reserve rules before creating a review.
- Sign the NSAT TransactionV0 envelope on-device. `/api/wallet/submit/` relays only an already signed envelope to the fixed NSAT gateway; it does not receive or persist the key.
- Track the exact transaction hash using `/api/wallet/confirmation/<hash>/`. The app never treats a gateway acceptance as confirmation and never rebroadcasts automatically after an ambiguous result.

## Protocol compatibility

The browser transaction builder is checked against the NSAT transaction vector in `satoshicore-mac/Tests/NSATCoreTests/Resources/vectors.json` from the local NSAT-Core source checkout. It uses the NSAT TransactionV0 format and Stellar-compatible Ed25519 keypairs. This validates the encoding/hash/signature path; it is not a production transaction test.

## Safety and trust boundaries

- Payment requests carry a public address and amount only. They are not identity verification or spending authorization.
- Each transfer requires an explicit review and confirmation. Opening a request never sends funds.
- The server permits only authenticated requests and applies a per-user `wallet_send` throttle. The upstream destination is fixed in server code; arbitrary proxy URLs are not accepted.
- Mainnet identity and account state are read again immediately before signing. A changed balance, sequence, fee, or destination state invalidates the review.
- A network timeout after signing is shown as unknown. The user must check the exact hash; the app does not create a replacement automatically.
- The local recovery key must be backed up by the user. Clearing browser storage or losing the password without the recovery key can permanently lose access. Browser encryption does not protect against a compromised device or same-origin script execution.
- New recipient payments use the live Mainnet `zeroReserveProtocol` policy. On current NSAT Mainnet, the ledger reports zero reserve for a new account, so a marketplace payment may create a recipient with the listed amount; the wallet must not invent a 2× base-reserve minimum. Where zero-reserve policy is unavailable, preflight falls back to the live base-reserve minimum. Free self-open is a separate owner-signed path. An active source account retains the reserve floor reported by live policy, and the live network base fee must equal the reviewed 10 NSAT policy. A changed fee policy blocks signing.

## Verification boundary

Automated protocol-vector, keystore, API, and isolated/mock-ledger tests are required before release. A real Mainnet send requires an explicit user-selected recipient and amount and is not part of automated tests. Do not claim a successful live transfer from build or mock tests alone.
