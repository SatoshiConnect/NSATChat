# Creator marketplace, wallet boundary, and NFT readiness

## Current implementation boundary

The Marketplace app provides an authenticated catalog, reviewed creator submissions, NSAT checkout, user-owned entitlements, creator activity notices, user reports, staff moderation, and audit records.

A purchase is now a real NSAT order:

1. `POST /api/marketplace/items/<id>/orders/` prices the listing, snapshots the creator/platform split, resolves payee addresses from verified `WalletLink` records, and returns one transfer per role to be signed.
2. The buyer signs each transfer on their own device in the Messenger wallet and posts only the signed envelope to `/api/marketplace/orders/<id>/payments/<role>/`.
3. The server re-verifies the envelope (Mainnet identity, signature, source = linked buyer address, payee, exact amount) before relaying it to the NSAT gateway.
4. `GET /api/marketplace/orders/<id>/` polls the indexer. The entitlement, creator sale record, notification, and audit entry are written only when every required transfer is confirmed.
5. `python manage.py settle_marketplace_orders` reconciles submitted orders for buyers who closed the app, and expires abandoned ones. Run it from cron every minute or two in production.
6. When an order becomes paid the buyer's inbox socket (`chat_inbox_<user id>`) receives `marketplace.order_paid`; the client shows a toast and reloads My library, so access unlocks even if checkout was closed. Delivery is best-effort — REST polling and the settlement command remain the source of truth.
7. Before signing, checkout states that the payment is final (no reversal or refund by NSATChat), that a 10 NSAT network fee applies to each transfer, and that the rest goes directly to the creator.
8. `python manage.py reconcile_marketplace` audits the ledger against the chain and writes an admin report; see “Reconciliation (chain vs ledger)”.

Paid inventory is separate from the legacy demo: `MarketplaceOrder`, `OrderPayment`, `MarketplaceEntitlement`, and `CreatorSale` are new tables, and `SimulatedPurchase`/`InventoryItem` are untouched. The old no-payment endpoint is disabled unless `MARKETPLACE_ALLOW_SIMULATED_PURCHASES=true`.

## Settlement rules

- Platform fee is **0 basis points** (decided for launch), so the creator receives the entire listing price and no treasury address is needed. Integer-only split; the parts always sum to the listing price, and a 100% fee is rejected.
- If the fee is above 0, a valid `MARKETPLACE_TREASURY_ADDRESS` is required or order creation fails closed with `marketplace_misconfigured` (503).
- Orders expire after `MARKETPLACE_ORDER_TTL_SECONDS` (default 15 minutes). A late signature is refused before any gateway call.
- One open order per buyer and listing, enforced under a per-buyer row lock so two tabs checking out at the same time cannot open two payable orders; `idempotency_key` replays the same order and a reused key for another item is a conflict.
- A transfer is refused with `409 already_owned` before the gateway call if the buyer already owns the item through another order, so a duplicate order can never take a second payment and grant nothing.
- One submitted envelope per role and order; the transaction hash is derived server-side from the verified payload, never trusted from the client.
- A signed transfer is usable once, globally. Reusing it for another order returns `409 payment_already_used`, checked before submission and enforced again by the unique transaction hash so a racing request is refused cleanly instead of returning a server error.
- A failed confirmation marks the order `failed`; a partially confirmed multi-transfer order stays `partially_paid` and grants nothing.
- Creator must have a linked wallet and must not be the buyer; listings without the required wallets report `purchase_mode: "closed"` in the catalog.
- Paid access is independent of the listing's sale state. Disabling a listing stops new sales but buyers keep what they bought; access ends only through the audited `services.revoke_entitlement` (the “Revoke selected entitlements” admin action), which records the reason, writes an audit event, and notifies the buyer. A mistaken revocation is undone with the matching `services.restore_entitlement` admin action; both events stay in the audit trail and the buyer is notified. Legacy simulated grants still require an approved listing.
- `CreatorSale` outlives the buyer account: deleting a buyer removes their orders and entitlements, but the creator's sales history keeps the amounts, the on-chain hash, an `order_reference`, and a non-reversible `buyer_reference` for reconciliation.

## Reconciliation (chain vs ledger)

Checkout and `settle_marketplace_orders` move a payment forward while someone is
watching. The reconciliation pass proofreads the books instead: it compares what
the indexer reports about the chain with what the ledger recorded and leaves an
admin-readable report for every gap it finds.

```bash
python manage.py reconcile_marketplace                  # audit and repair what is safe
python manage.py reconcile_marketplace --dry-run        # report only
python manage.py reconcile_marketplace --skip-chain-check
python manage.py reconcile_marketplace --fail-on-issues # non-zero exit for cron alerting
```

Each pass writes a `MarketplaceReconciliationRun` plus one
`MarketplaceReconciliationIssue` per finding. Both are read-only in Django admin
(**Marketplace → Marketplace reconciliation runs**), where the changelist shows
the scan counts, critical count and repairs, and the row shows each issue with
its order reference and whether it was repaired. Staff can also run a pass from
the admin action “Run a reconciliation pass now”; the run records who did it.

What the pass checks:

- **Submitted transfers** are handed to the normal settlement path, so a transfer
  the chain confirmed after the buyer closed the app becomes a paid order with
  its entitlement, sale record and realtime unlock. Reported as
  `order_settled_late` (repaired).
- **Paid order invariants**: transfers must total the order price, every transfer
  must be confirmed, and the sale record must match the order snapshot. A paid
  order missing its entitlement or sale record is repaired (`order_missing_entitlement`
  is critical, `order_missing_sale` is a warning); amount and confirmation
  disagreements are reported and never rewritten.
- **An order whose transfers all confirmed but which never became paid** is
  critical (`order_fully_paid_but_open`): the money is in and access was missed.
- **A closed order that still holds a confirmed transfer** is critical
  (`closed_order_with_confirmed_payment`): fail-closed settlement can close a
  multi-transfer order after one transfer failed while another one confirmed,
  and that money must be examined by a human. Nothing is rewritten.
- **Active entitlements without a paid order** are critical (`entitlement_without_paid_order`):
  access exists but no confirmed settlement backs it.
- **Reorg re-check**: confirmed transfers from the last
  `MARKETPLACE_RECONCILIATION_RECHECK_DAYS` days (default 7, 0 disables) are read
  again, least recently verified first (each transfer records
  `chain_checked_at`), so a busy week cannot push older transfers permanently
  out of the page; one the chain no longer confirms is reported as
  `payment_no_longer_confirmed`. Access is not revoked automatically — a human
  decides, because a reorg can resolve itself.
- A transfer unconfirmed for `MARKETPLACE_RECONCILIATION_STALE_MINUTES` (default
  30) is reported as `payment_stalled`.

A run whose process dies is closed as failed by the next pass (after 60
minutes) instead of staying “running” in the report forever.

The pass never moves money and never rewrites an amount, a payment state or a
confirmation, so a disagreement stays visible until someone acts on it. Run it
after settling (hourly is enough) with `--fail-on-issues` so a gap pages instead
of waiting for the buyer who cannot open what they paid for. Repairs write an
`order.repaired` audit event and, when access was restored, notify the buyer
over their inbox socket.

## Wallet adapter contract

The Messenger wallet is the only signer:

- `readAddress()` and `readBalance(asset)` query only the wallet the user linked to their account.
- `requestSignature` shows the exact payee and amount and requires explicit approval for each transfer; the decrypted secret lives only in the wallet component.
- The backend stores transaction hashes, amounts, roles, and state — never private keys, seed phrases, or signing tokens.
- The legacy purchase simulation is not a payment endpoint and is off by default.

## Live settlement decisions

Live settlement is **off in code by default** (fail-closed): taking real money must be an explicit operator decision. It is enabled only through the deployment environment, by setting `MARKETPLACE_LIVE_PAYMENTS=true` in `.env.prod` (see `.env.example`). While the flag is off, order creation returns 503 and the catalog reports listings as not for sale; the buyer and creator UI is unchanged and works as soon as the flag is on.

The platform fee is **0%**, so every sale pays the creator directly and there is no treasury address to configure. A creator cannot be paid until they connect a wallet, and the catalog reports such listings as not for sale.

Operators should still, before promoting the marketplace publicly:

1. Confirm the production NSAT network identity (`NSAT Mainnet ; October 2026 ; bc3098829fffc717`) and signing format against protocol owners and multiple trusted nodes; the verifier enforces that exact network hash.
2. Complete threat modeling, independent security review, key custody review, and incident/rollback procedures.
3. Establish legally reviewed terms, creator payout rules, refund/dispute process, sanctions/tax handling, and fee disclosures for each target jurisdiction.
4. Publish at least one real listing with `python manage.py publish_marketplace_item --creator <phone> --title ... --price <nsat> --assets <dir> --approve` and have the creator connect a wallet.
5. Schedule `settle_marketplace_orders` every minute or two and `reconcile_marketplace --fail-on-issues` hourly (cron or a worker beat), and keep `MARKETPLACE_ORDER_TTL_SECONDS` low enough that abandoned orders clear quickly. Watch the reconciliation runs in admin; a critical issue means the ledger and the chain disagree.
6. Run a staging payment end to end: pending, confirmed, failed, expired, duplicate submission, and a two-transfer (fee) order, including a two-account check that an unpaid account cannot read another buyer's order.

### Testing the concurrent path

The settled-transfer race is covered on PostgreSQL; SQLite's shared cache refuses
concurrent writers with a table lock before the unique constraint can decide.

```bash
TEST_DATABASE_URL=postgres://mhtalk:mhtalk@127.0.0.1:5432/mhtalk_test \
DJANGO_SETTINGS_MODULE=config.settings.test_postgres \
python manage.py test apps.marketplace apps.wallet_integration
```

CI runs the same suite against its PostgreSQL service, where the threaded test
asserts exactly one `200` and one `409 payment_already_used`.

If a fee is introduced later, `MARKETPLACE_PLATFORM_FEE_BPS` and `MARKETPLACE_TREASURY_ADDRESS` must be set together; a fee without a treasury intentionally blocks all sales rather than guessing a destination. Buyers can reopen an unpaid order from My library, and creators see confirmed sales totals in Creator studio.

## NFT / on-chain item status

No NFT token standard is assumed or implemented. The inspected public SatoshiCore/NSAT source does not establish an official NFT interface or ownership/indexing standard; third-party asset protocols are not evidence that NSAT itself supports those standards. Entitlements are app inventory backed by a confirmed payment, not chain ownership.

Before NFT readiness can become an implementation, protocol owners must publish/confirm: official asset type and identifier format, mint/burn/transfer rules, metadata schema and immutable-field policy, ownership proof and finality rules, indexer/API contract, media persistence/content-addressing guarantees, royalties/payout semantics, spam/abuse controls, wallet signing format, and testnet fixtures.

## Scope limitations

- Gifts remain app-level and simulated; they are not paid transfers.
- Creator notices are stored for the dashboard; they are not yet delivered through Web Push or the real-time chat notification channel.
- Refund and dispute flows for settled NSAT payments are not implemented; a settlement is final once the indexer confirms it. The report/review audit trail is present.
- Creator sticker packs can include up to 30 uploaded images (2 MB each). After a confirmed payment, only the owning account receives the full sticker asset list in the chat sticker picker, together with legacy inventory grants.
- Preview upload accepts image formats only and limits files to 5 MB at the API serializer. Production storage scanning/CDN policy must still be verified.
