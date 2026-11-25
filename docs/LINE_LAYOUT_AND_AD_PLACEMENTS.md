# NSATChat layout patterns inspired by LINE

This is a product adaptation, not a pixel copy of LINE. Keep NSATChat's own
brand, accessibility, privacy, and wallet-signing rules.

## Current screen map

| NSATChat surface | LINE pattern adapted | Current behavior |
| --- | --- | --- |
| Home | Home as a people and services hub | Profile, quick actions, a marketplace spotlight poster, and friend preview |
| Chats | Chat list with in-context Friends access | Conversation filters; phone layout switches between Chats and Friends; calls remain in conversations and call history cards |
| OpenChat | Community destination | Current implementation is invite-only joined groups; public discovery is not available yet |
| Today | Stories/status plus persistent social posts | Status row and social feed share the discovery surface |
| Wallet | Wallet and commerce gateway | Wallet and Marketplace share one bottom destination and have an in-page switcher |

LINE's current redesign is regional and gradual. Its official help documents a
Friends tab in Chats and, for Thailand, an OpenChat tab replacing VOOM. We use
the interaction patterns where they fit NSATChat; we do not assume every LINE
account has the same navigation.

## Sponsored-content placement policy

`AdPlacement` is a first-party, plain-text creative surface. Empty placements
stay hidden. It does not fetch campaigns, render third-party HTML, or send
tracking events. A campaign API, moderation flow, billing, and privacy review
are still required before ads can appear to users.

Prepared placements:

- `chat-list-top`: one compact card at the top of the conversation list.
- `home-discovery`: reserved for moderated ad campaigns after profile shortcuts. It remains hidden until a campaign API exists.
- `social-feed-inline`: between the post composer and feed results.
- `marketplace-discovery`: in browse only, never on Wallet balance, send, or checkout screens.

Do not place ads inside direct or group message history, call screens, contacts,
AI answers, wallet balances, transaction signing/confirmation, or payment error
dialogs. Ads must carry a visible “Sponsored” label and use approved image and
link fields; never accept arbitrary HTML or scripts.

## Before enabling paid campaigns

1. Add an authenticated campaign API and moderation/admin controls.
2. Define frequency caps, dismissal, targeting consent, retention, and reporting.
3. Add click/impression measurement with privacy and fraud controls.
4. Confirm ad assets are optimized and accessible on narrow screens.
5. Keep checkout and wallet transaction UI ad-free and stable.

The visible Home poster currently features the first approved marketplace item
(or a SatoshiCore discovery card when the catalog is empty). It is a first-party
spotlight, not a paid ad. Admin-managed poster campaigns still need a campaign
model, upload/review controls, and scheduling before advertisers can use the
reserved `home-discovery` placement.

Official references:

- [LINE app redesign help](https://help.line.me/line/smartphone?contentId=200001630&lang=en)
- [LINE Ads placement overview](https://www.lycbiz.com/sites/default/files/media/jp/download/EN_LINE%20Business%20Guide_202404-09_summary.pdf)
