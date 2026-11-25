# OpenChat product research and NSATChat adaptation

Research date: 25 November 2026

Scope: official LINE OpenChat guide and Help Center compared with the current NSATChat repository.

## Recommendation

Treat OpenChat as a community product built on the existing chat engine, not as another label for ordinary private groups. Keep current invite-only group chats private and unchanged. Introduce an explicit community record and publication controls before adding public search or discovery. The first major release should make communities discoverable and safe to join; high-scale live audio should come later because the current group-call mesh is limited to eight participants.

## What LINE OpenChat provides

| Area | LINE pattern | Product value |
| --- | --- | --- |
| Discovery home | Search, recommendations, categories, hot topics, trending/ranking, joined rooms, and create entry points | Lets people find rooms without already having an invite |
| Room preview | Room name, cover, description, member count, rules, and join method before joining | Helps people decide before exposing themselves to a room |
| Access | Public join, join code, or admin approval with questions | Gives room owners graduated control |
| Identity | Nickname and avatar can differ per OpenChat and do not change the main LINE profile | Supports interest-based pseudonyms while retaining the account's main identity privately |
| Management | Owner and co-admin roles, permission controls, and member-cap settings | Makes larger communities manageable |
| Organization | Notes, important/pinned notes, polls, events, reactions, subchats, and threads | Keeps announcements and focused discussion from being lost in a fast timeline |
| Live audio | Host, speakers, listeners, and reporting; LINE documents up to 10,000 listeners and up to 100 speakers | Supports events at a scale beyond ordinary group calls |
| Safety | Reporting, policy review, visibility restrictions, and automated support for inappropriate-content handling | Discovery is governed by trust and moderation, not just search indexing |
| Web access | Official OpenChat website complements mobile and desktop app discovery | Supports sharing and discovery outside the app |

Availability and limits can vary by region and LINE version. The guide is a product reference, not a requirement to copy LINE's implementation or branding.

## Current NSATChat state from source

### Implemented foundation in the current feature branch

OpenChat now has a separate `OpenCommunity` record linked to a group room.
New communities start pending moderation review; existing groups are not
backfilled into public discovery. The app has discovery search and category
filters, a My OpenChats view, create flow, public/code/approval join modes,
room-only nicknames, request review for community admins, and community
reporting. The existing group room continues to provide messages and calls.

Community member/message serializers suppress account phone, email, public ID,
and the main profile display name in this context; the community nickname is
used instead. Join codes are hashed. Admins approve/suspend listings in the
Django admin, and reports are reviewed there. The migration must be applied
before these API routes work on a server.

This is the first usable community slice, not the full LINE feature set. It
does not yet include a community cover/nickname avatar editor, configurable
join questions, public message previews, owner self-service edit/moderation,
in-app report queue, member bans/capacity controls, recommendation/trending
ranking, subchats/threads/events, or large-audience live audio.

| Capability | Current state |
| --- | --- |
| OpenChat screen | `OpenChatPanel.jsx` provides published-community discovery, category/name search, expandable metadata/rules, My OpenChats, and create entry. |
| Community data | `OpenCommunity` links one group room to a review state, category, join mode, discoverability, preview setting, rules, tags, and a hashed optional join code. |
| Invitations | Existing group invite codes have high entropy, are resettable, and preview/join endpoints are authenticated and rate limited. This is a useful private-invite foundation. |
| Membership/admin | Existing group admins can review approval requests. OpenChat creators start as room admins; group-level permission controls are reused. New owners can choose a separate room nickname. |
| Conversation engine | Existing messaging features include real-time chat and group features such as calls, reactions, polls, and mentions. These can be reused where appropriate. |
| Moderation | Public discovery is limited to published/searchable records; new listings are pending by default. Members can report a community; admins publish/suspend listings and review reports in Django admin. There is no in-app moderation queue yet. |
| Not yet present | Recommendation/trending, public message previews, join questions, community cover/avatar editing, bans/capacity, owner self-service settings, subchats, threaded replies, community notes/events, message reporting, and stage-style live audio. |

Public search must continue to use only explicitly published community records;
it must never list every `ChatRoom` with `room_type=GROUP`.

## Proposed NSATChat product shape

### OpenChat landing screen

1. Search field searches only approved, published communities and their public metadata.
2. Compact category chips lead to paginated category results.
3. A small “Recommended” row uses explicit, explainable signals (category match, recent healthy activity, and quality/moderation state).
4. A “Trending” list is rate-limited and fraud-resistant; do not rank by raw message volume alone.
5. “My OpenChats” separates joined rooms, pending join requests, and invitations.
6. Create entry starts a guided community setup, separate from the existing “New private group” flow.
7. Any paid placement in discovery is clearly labeled Sponsored and separated from organic ranking. In-room ad space remains compact and outside message history and the composer.

### Community detail and joining

Show cover, title, category, owner/moderator, description, guidelines, member count, recent public preview if enabled, access mode, and report action before joining. Joining should offer a room-specific nickname/avatar. Do not reveal account phone, email, or main-profile details to other community members by default.

Support three access modes in a new community workflow:

- **Public:** join immediately, subject to rate limits and room capacity.
- **Code:** verify a community-specific join code; store a verifier/hash rather than a reusable plaintext code and never log submitted codes.
- **Approval:** submit a request (and optional owner-defined questions), show pending state, and allow cancellation. Only admins can approve or reject.

Keep the existing private invite link separate from public search and from community join codes.

### Room identity, roles, and controls

- Store a participant's optional community nickname/avatar separately from the account profile. Room identity must be used consistently in messages, replies, member lists, notifications, and moderation evidence.
- Add an owner and scoped moderator roles. Enforce every permission on the backend; hiding controls in React is not authorization.
- Provide member removal/ban, report handling, invite/reset controls, message permission, room metadata editing, discovery toggle, preview toggle, member cap, and audit history.
- Room owners can publish editable rules and pin one announcement. Avoid a separate notes product in the first release; reuse the existing message/post primitives only if permissions and retention remain clear.

## Suggested data/API boundary

Keep `ChatRoom` as the conversation/message transport. Add a distinct community domain linked one-to-one to an eligible group room, for example:

- `OpenCommunity`: status (`draft`, `pending_review`, `published`, `suspended`), category, tags, rules, discoverability, preview permission, join policy, capacity, and moderation timestamps.
- `OpenCommunityProfile`: room-specific nickname/avatar tied to a participant.
- `OpenCommunityJoinRequest`: requester, answers, state, reviewer, and timestamps, with uniqueness and rate limits.
- `OpenCommunityReport` plus an auditable moderation action record.

Do not add searchable flags or public categories directly to every existing `ChatRoom` without an explicit migration/backfill policy. Default all existing rooms to private and unlisted. Public catalog APIs must filter to approved `published` records, return minimized fields, paginate, throttle, and exclude blocked/suspended or otherwise restricted rooms. Search should never return message bodies from private rooms.

## Phased delivery

| Phase | Deliverable | Release gate |
| --- | --- | --- |
| 0. Rules and safety | Community guidelines, reporting reasons, retention policy, admin review process, safe defaults, and feature flags | No public listing until there is a staffed response path for abuse reports |
| 1. Community foundation | Explicit community model, private-by-default migration, create/edit flow, category/cover/rules, room profile, public/code/approval joins, preview and join-request states | Backend permission and privacy tests; legacy private groups remain private |
| 2. Discovery | Search, categories, recommendations, trending, community cards/detail, My OpenChats and pending requests | Pagination, throttling, abuse ranking defenses, keyboard/mobile responsive review |
| 3. Governance | Owner/moderator roles, report queue, member controls, audit log, spam/rate limits and moderation holds | Abuse-response workflow and admin access review |
| 4. Community utilities | Announcements, reusable polls, scheduled events, room-specific search, then threads/subchats based on measured need | Each feature has deletion, retention, notification, and authorization behavior specified |
| 5. Live audio scale | Community stage with host/speaker/listener roles and report controls | Requires an SFU and capacity/cost/operations plan; current mesh call limit is not a 10,000-listener architecture |
| 6. Monetization | Sponsored discovery cards, creator/community promotions, frequency caps and billing/audit | Clear labeling, consent/privacy review, moderation, fraud controls, and ad management UI |

## Non-negotiable privacy and safety checks

- Existing private rooms remain private unless an owner explicitly creates/publishes a community and completes the required settings.
- Room-specific names and pictures cannot change or disclose the user's main account profile.
- Public previews are opt-in and contain only explicitly approved room metadata/content.
- Join endpoints must prevent duplicate memberships, enumeration, code brute force, request spam, and capacity races.
- Reports must preserve enough evidence for review while minimizing retention and restricting access.
- Search/ranking must support suspension and rapid removal; do not reveal internal moderation criteria that enable evasion.
- Do not send community messages to Gemini or other AI services for moderation unless there is a distinct, disclosed policy and explicit legal/privacy review.
- Ads must not be mixed into private message history or shown in signing/payment flows. Avoid behavioral targeting based on message content.

## First-release acceptance criteria

1. A user can create an explicitly public, code-gated, or approval-gated community without changing ordinary private-group creation.
2. Existing groups are absent from public discovery unless their owner deliberately publishes them.
3. A signed-out or non-member preview reveals only approved community metadata; private messages remain unavailable.
4. Users can choose a separate community nickname/avatar and see that identity used in all community surfaces.
5. Approval requests can be reviewed, rejected, cancelled, and rate limited; code join does not expose secrets in logs.
6. Users can report a community/message and admins can review, act, and audit the outcome.
7. Search and category results are paginated, mobile responsive, and keyboard accessible.
8. Existing group chat, calls, wallet, and ordinary group permissions remain unchanged.

## Official references

- [LINE OpenChat official Thai guide](https://openchat.line.me/th/guide) — discovery home, search, categories, trending, joined rooms, room creation, access modes, per-room profile, notes, announcements, moderation, and community features.
- [LINE Help Center: OpenChat participant basics](https://help.line.me/line/smartphone?contentId=20005375&lang=en) — join/search/invite behavior and community profile concepts.
- [LINE Help Center: OpenChat administrator basics](https://help.line.me/line/smartphone?contentId=20005393&lang=en) — owner and co-admin roles and settings.
- [LINE Help Center: Live Talk](https://help.line.me/line/?contentId=20024812) — host/speaker/listener roles, reporting, and documented scale limits.
- [LINE Help Center: OpenChat search visibility restrictions](https://help.line.me/line/smartphone?contentId=20024174&lang=en) — safety and policy controls over search visibility.
