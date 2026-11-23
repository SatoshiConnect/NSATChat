# Creator Economy Architecture

## Current boundary

The existing `apps/marketplace` module owns digital item submissions, moderation state, simulated purchase records, app inventory, creator gift events, reports, creator profiles and audit events. `apps/status` owns ephemeral updates that expire after 24 hours. There is no persistent social post/feed model yet, so marketplace gifts currently attach to visible Status updates only.

## Sticker-pack path

1. A signed-in creator submits a `sticker_pack` item with one to thirty image assets (maximum 2 MiB each).
2. The item and assets enter the existing moderation flow; pending and disabled listings are excluded from the public catalog and entitlement endpoint.
3. An approved listing may be added to a user library through the existing explicitly labelled simulation flow. This creates an app inventory record and does not charge NSAT.
4. `GET /api/marketplace/stickers/mine/` returns full pack assets only where the authenticated account has an inventory grant for an approved sticker pack.
5. The chat picker combines those owned packs with existing built-in and device-local stickers. Sending still uses the established chat `STICKER` message/upload pipeline.

Marketplace data remains in the Marketplace module; the chat picker consumes a read-only marketplace contract and does not duplicate inventory state. URLs may use the existing media storage/CDN configuration.

## Payment and ownership boundary

Proposed NSAT prices and simulated purchases are display/application state. No wallet signing, private key handling, live debit, payout, NFT minting, or chain ownership claim is added. A future payment adapter must require user-controlled signing approval per transaction and independently verified network/recipient/fee/finality data.

## Social product gap

“My Status” is the 24-hour Status/Stories feature, with audience controls, view receipts and replies/reactions delivered to private chat. It is not a persistent post feed and does not currently provide durable posts, comments, share/repost, or feed ranking. Those are separate product modules and should not be represented as complete by the Status implementation.
