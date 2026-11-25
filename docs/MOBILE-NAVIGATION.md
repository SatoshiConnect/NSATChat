# Mobile navigation

The phone bottom bar uses six distinct destinations:

1. **Home** — profile, friend shortcuts and a compact friends preview. Full
   friend management is also available from Home.
2. **Chats** — chat list with a **Chats / Friends** switcher. Voice and video
   calls remain available in conversations; there is no separate Calls tab.
3. **OpenChat** — discover and join public communities, plus manage community
   join requests. Existing private groups remain private and are not listed.
4. **Today** — editorial news and current affairs from the official
   Thailand.go.th RSS feed. Headlines link to their publisher and are cached
   briefly; member-created posts never appear here.
5. **Social** — member Stories and persistent social posts.
6. **Wallet** — Wallet and Marketplace through the section switcher.

Settings and profile are reached from Home. Marketplace remains paired with
Wallet, and calls remain part of Chats. Do not restore redundant Calls,
Contacts, Profile or Settings bottom tabs. The desktop rail remains more
expansive and keeps direct access to Wallet, Marketplace, Contacts and AI.

Implementation points:

- `frontend/src/components/navigation/NavRail.jsx` defines the mobile and
  desktop destinations.
- `frontend/src/components/layout/MainLayout.jsx` wires Home, Chats, OpenChat,
  Today, Social and Wallet sections.
- `frontend/src/components/layout/TodayNewsPanel.jsx` renders the separate
  editorial news destination.
- `apps/news/views.py` fetches the fixed official RSS source, limits and parses
  feed data, caches it, and serves only today's headlines in Bangkok time.
- `frontend/src/components/layout/MobileChatsPanel.jsx` provides the mobile
  Chats / Friends switcher.
- `frontend/src/components/chat-list/OpenChatPanel.jsx` provides community
  discovery and a My OpenChats view; only explicitly published, searchable
  communities appear in discovery.
- The OpenChat API requires its new Django migration before deployment. New
  community listings remain pending until an admin approves them.
- `frontend/src/styles/layout.css` owns the responsive switchers and tab bar.

See [OpenChat product research and NSATChat adaptation](OPENCHAT_PRODUCT_RESEARCH.md)
for the LINE feature comparison, current code audit, privacy boundaries, and
phased implementation plan. Existing invite-only groups must remain private by default.

If `VITE_FEATURE_WALLET_UI=false`, the Wallet destination is **Market** and
opens Marketplace directly; it never points to a disabled Wallet screen.

## Host-proxy deployment note

In host-proxy mode, Caddy must serve `/`, `/manifest.webmanifest`, and `/sw.js`
from the same active checkout's `frontend/dist` directory that
`deploy/deploy.sh` replaces. If these roots point to a separate staging
checkout, an older bundle can overwrite the new mobile navigation after a
deploy. Check the live HTML's hashed JS asset after deployment and confirm it
contains the current navigation labels before calling the UI update complete.
