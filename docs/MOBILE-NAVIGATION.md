# Mobile navigation

The mobile bottom bar is intentionally condensed to five destinations:

1. **Chats** — chat list and the **Chats / Calls** section switcher.
2. **Updates** — status and social updates.
3. **Contacts** — friends and contact discovery.
4. **Wallet** — the **Wallet / Marketplace** section switcher.
5. **You** — profile and settings.

Calls and Marketplace are grouped to save persistent space on phone screens;
they remain full sections with their existing screens and features. Do not add
them back as separate mobile bottom-bar destinations. Desktop navigation keeps
its separate Calls and Market shortcuts.

Implementation points:

- `frontend/src/components/navigation/NavRail.jsx` defines the mobile and
  desktop destinations.
- `frontend/src/components/layout/MainLayout.jsx` renders the mobile section
  switchers and retains the existing section routing.
- `frontend/src/styles/layout.css` owns the responsive switcher and tab-bar
  presentation.

The Wallet destination and the Wallet option in its mobile section switcher
appear only when `VITE_FEATURE_WALLET_UI` is enabled. If Wallet is disabled,
Marketplace remains directly available as **Market** without a dead Wallet tab.

## Host-proxy deployment note

In host-proxy mode, Caddy must serve `/`, `/manifest.webmanifest`, and `/sw.js`
from the same active checkout's `frontend/dist` directory that
`deploy/deploy.sh` replaces. If these roots point to a separate staging
checkout, an older bundle can overwrite the new mobile navigation after a
deploy. Check the live HTML's hashed JS asset after deployment and confirm it
contains `mobile-section-switcher` before calling the UI update complete.
