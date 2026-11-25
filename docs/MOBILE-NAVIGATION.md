# Mobile navigation

The phone bottom bar uses five destinations inspired by LINE:

1. **Home** — profile, friend shortcuts and a compact friends preview. Full
   friend management is also available from Home.
2. **Chats** — chat list with a **Chats / Friends** switcher. Voice and video
   calls remain available in conversations; there is no separate Calls tab.
3. **OpenChat** — joined group rooms that use invitation links. Public group
   discovery and searchable public communities are not implemented yet; the
   screen states this limitation and does not imply that private rooms are
   publicly discoverable.
4. **Today** — Stories and persistent social posts in one scrollable feed.
5. **Wallet** — Wallet and Marketplace through the section switcher.

Settings and profile are reached from Home. Marketplace remains paired with
Wallet, and calls remain part of Chats. Do not restore redundant Calls,
Contacts, Profile or Settings bottom tabs. The desktop rail remains more
expansive and keeps direct access to Wallet, Marketplace, Contacts and AI.

Implementation points:

- `frontend/src/components/navigation/NavRail.jsx` defines the mobile and
  desktop destinations.
- `frontend/src/components/layout/MainLayout.jsx` wires the Home, Chats,
  OpenChat, Today and Wallet sections.
- `frontend/src/components/layout/MobileChatsPanel.jsx` provides the mobile
  Chats / Friends switcher.
- `frontend/src/components/chat-list/OpenChatPanel.jsx` currently lists joined
  invite-based groups; it is not a public group directory.
- `frontend/src/styles/layout.css` owns the responsive switchers and tab bar.

If `VITE_FEATURE_WALLET_UI=false`, the fifth destination is **Market** and
opens Marketplace directly; it never points to a disabled Wallet screen.

## Host-proxy deployment note

In host-proxy mode, Caddy must serve `/`, `/manifest.webmanifest`, and `/sw.js`
from the same active checkout's `frontend/dist` directory that
`deploy/deploy.sh` replaces. If these roots point to a separate staging
checkout, an older bundle can overwrite the new mobile navigation after a
deploy. Check the live HTML's hashed JS asset after deployment and confirm it
contains the current navigation labels before calling the UI update complete.
