# Creator marketplace, wallet boundary, and NFT readiness

## Current implementation boundary

The Marketplace app provides an authenticated catalog, reviewed creator submissions, user-owned inventory, simulated purchases, simulated gifts attached to visible Stories, creator activity notices, user reports, staff moderation, and audit records. Every purchase and gift response is explicitly marked as a simulation. The Marketplace never calls the wallet transaction submit endpoint and does not hold signing material.

The current listing price is display-only proposed NSAT. A simulation can add a digital item to the local application inventory, but it does not debit a wallet, create a chain transaction, or promise transferability. Starter catalog entries are app-native examples with personal in-app use rights.

## Wallet adapter contract

Any future integration must be a client-side, headless adapter with separately declared capabilities:

- `readAddress()` and `readBalance(asset)` may only query a wallet the user has explicitly linked.
- `requestSignature({ asset, amount, recipient, nonce, expiresAt })` must display exact transaction details in the wallet-controlled context and require explicit user approval for each transaction.
- Messenger backend may store transaction identifiers and state, never private keys, seed phrases, or signing tokens.
- Payments must be disabled unless the wallet provider, chain identity, recipient validation, fee display, replay protection, idempotency, confirmation verification, and recovery flows are independently reviewed.
- The Marketplace purchase simulation endpoint is not a payment endpoint. Do not change it to make a server-side wallet call.

## Required before real payments or payouts

1. Confirm the production NSAT network and chain ID with protocol owners and verify it from multiple trusted nodes.
2. Confirm wallet signing behavior and transaction serialization against official protocol and wallet specifications.
3. Complete threat modeling, independent security review, key custody review, replay/idempotency review, and incident/rollback procedures.
4. Establish legally reviewed terms, consumer disclosures, creator payout rules, refund/dispute process, sanctions/tax handling where applicable, and fee disclosures for each target jurisdiction.
5. Run staging-only end-to-end payments with test assets, including pending, confirmed, failed, reorg/timeout, duplicate submission, and refund/dispute paths.
6. Obtain an explicit product approval to enable live payment configuration. This task does not enable it.

## NFT / on-chain item status

No NFT token standard is assumed or implemented. The inspected public SatoshiCore/NSAT source does not establish an official NFT interface or ownership/indexing standard; third-party asset protocols are not evidence that NSAT itself supports those standards. No contracts, token standards, metadata schemas, or consensus behavior were added.

Before NFT readiness can become an implementation, protocol owners must publish/confirm: official asset type and identifier format, mint/burn/transfer rules, metadata schema and immutable-field policy, ownership proof and finality rules, indexer/API contract, media persistence/content-addressing guarantees, royalties/creator payout semantics, spam/abuse controls, wallet signing format, and testnet fixtures. A future marketplace may record off-chain app inventory first, but must not label that inventory as an NFT or chain ownership.

## Scope limitations

- Gifts currently attach to a visible Story/Status; there is no general social-post model in this repository, so post and future video-feed integrations await those modules.
- Creator notices are stored for the dashboard; they are not yet delivered through Web Push or the real-time chat notification channel.
- Refund/dispute states for actual payments are intentionally absent because no real payment exists. The audit trail and report review foundation is present.
- Sticker packs and other digital goods are catalog/inventory records; the existing chat sticker picker remains its static pack source until a reviewed entitlement-to-sticker-packs integration is implemented.
- Preview upload accepts image formats only and limits files to 5 MB at the API serializer. Production storage scanning/CDN policy must also be verified.
