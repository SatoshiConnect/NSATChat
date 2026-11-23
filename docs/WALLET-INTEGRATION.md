# NSATChat native wallet

The Messenger Wallet is a first-party React feature rendered directly inside the NSATChat application. It must not embed or redirect to the separate `wallet.satoshicore.org` product.

## Current implementation boundary

- The UI can read an NSAT public address, exact whole-unit balance, and recent indexed activity through the authenticated `/api/wallet/read/` endpoint.
- A public address can be saved on the current device for convenience. It is watch-only: this does not prove ownership and cannot sign transactions.
- Receive shows the public address and a locally generated QR code. A private address or secret key must never be sent to the read API.
- One-to-one chats can carry a structured NSAT payment request. Selecting it opens the native Wallet section in the same Messenger app.
- The current server intentionally exposes read-only wallet data. No wallet generation, seed import, private-key storage, transaction construction, signing, or broadcast is implemented in NSATChat yet. The Send screen explains this limitation and submits no transaction.

## Requirements before enabling on-chain sending

1. Implement a new NSATChat-owned, non-custodial keystore. Generate keys with the device CSPRNG; encrypt at rest; keep seed/private-key material out of Messenger APIs, logs, chat messages, analytics, and backups unless the user explicitly chooses an audited encrypted backup.
2. Build transaction review and signing locally in the browser from a reviewed, version-pinned NSAT transaction SDK/protocol. Verify network identity, recipient, exact whole-unit amount, fee, sequence, and transaction hash before showing a separate confirmation step.
3. Submit only an already-signed envelope to a narrowly allowlisted relay. Never accept unsigned transaction instructions from the server as approval to spend.
4. Test key generation/import/recovery, wrong passwords, lock/idle cleanup, signature verification, transaction simulation, insufficient balance, replay/sequence handling, and Mainnet-safe failure behavior before enabling sends.
5. Keep payment requests descriptive and user-confirmed. Opening a request must not send funds automatically.

## Current trust boundaries

- The read API verifies the exact NSAT Mainnet identity before returning balances.
- Activity is public chain data; unavailable history is reported separately from the live balance.
- A payment request contains a public destination address authored by the chat sender. Treat it as a request that the payer must review, not as verified identity or payment authorization.
- The linked-wallet challenge API is legacy and is not used by the native Wallet UI. Remove its routes/models only in a separate data-safe migration after confirming no active production records or clients depend on them.
