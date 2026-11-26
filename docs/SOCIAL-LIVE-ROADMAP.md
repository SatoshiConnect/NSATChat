# Social Live: implementation boundary and production path

## What this codebase can do today

- Social already has authenticated posts, comments, reactions, follows, moderation reports, and chat presence.
- Group calling already exchanges WebRTC peer-to-peer media, with a hard limit of eight joined participants.
- The group call is a mesh call attached to a chat room. It is not a public broadcast service and its signaling does not relay or scale video for viewers.
- Marketplace sticker packs are owned as pack entitlements. They are reusable chat assets, not individually consumable gifts or transferable inventory.
- NSAT purchase flows already require the user to unlock and explicitly sign a transaction. A social reaction or sticker comment must not be presented as an NSAT donation.

## Safe rollout sequence

### Stage 1: social sticker comments

Allow a member to use a sticker from an owned Marketplace pack in a post comment or reply. The server verifies pack ownership on every submission. Unowned assets are rejected. A sticker-only comment is supported. Sending a comment sticker does not spend NSAT or consume the reusable pack entitlement.

Marketplace sticker packs are reusable entitlements today; the system does not enforce limited editions, serial numbers, or scarce per-sticker quantities. The picker should not label a pack “rare” unless a future inventory model actually enforces that supply limit.

### Stage 2: small live-session pilot

Only consider reusing the current mesh for a private, explicitly labeled pilot capped at the existing eight-person call limit. Add a distinct live-session record and audience policy rather than treating an ordinary chat call as a public stream. Clearly disclose the small audience limit and test mobile uplink, reconnect, moderation, host termination, and abuse controls before enabling discovery.

### Stage 3: scalable public broadcast

Public creator streams need a Selective Forwarding Unit (SFU) or another media relay, authenticated stream authorization, viewer chat fan-out, host/moderator controls, stream lifecycle handling, and capacity/abuse monitoring. This deployment currently has no configured SFU or broadcast media service. A mesh call must not be widened to public audiences as a substitute: each publisher would upload a separate stream to every viewer.

### Stage 4: paid gifts and donations

Keep reactions and ordinary owned-sticker comments free. A paid NSAT donation or gift needs its own explicit checkout, recipient and amount confirmation, idempotency key, signed wallet approval, chain submission and confirmation state, and immutable audit record. A Marketplace pack entitlement currently grants reusable access; transferring or consuming individual sticker items requires a separate inventory/quantity model. Never set a “reward” flag based only on a client request or show a donation as completed before chain confirmation.

## Go-live gates

1. Choose a media relay architecture and verify hosting capacity, bandwidth, privacy, retention, and operating cost.
2. Define host, co-host, viewer, moderator, block/report, and age/content policies.
3. Add audience chat rate limits, message moderation, and live-session abuse reporting.
4. For paid support, connect a server-created order to the existing wallet signing flow and grant creator activity only after verified settlement.
5. Load-test concurrent rooms, mobile network transitions, and service interruption; prepare rollback and account for SFU/network costs.

Until these gates are met, the app should describe live video, viewer donations, and paid live gifts as unavailable. The existing eight-person group call remains a separate feature.
