# Messenger and SatoshiCore Wallet

Messenger exposes the full SatoshiCore Wallet web application at
`https://wallet.satoshicore.org/messenger-embed/` inside its Wallet screen.
The embed is an origin-isolated Wallet route allowed only from
`https://chat.satoshicore.org`; transaction keys, unlock state, signing and
broadcasting remain inside the Wallet origin and its existing wallet engine.

## In-chat actions

- **Send NSAT** resolves the other participant's verified linked address via
  the authenticated room-scoped Messenger API and opens the embedded Wallet
  send screen with that address filled in. The user checks the recipient,
  amount, network and fee and explicitly signs in Wallet.
- **Receive NSAT** opens the Wallet receive screen, which shows the currently
  selected Wallet's public address and copy action. The Wallet can also be
  opened separately if the browser blocks framing or clipboard access.
- **Request NSAT** sends a regular Messenger message with a Wallet link. If the
  requester has a verified linked Wallet, the link opens the Wallet send screen
  addressed to the requester and may prefill an exact whole-number amount. The
  recipient reviews and approves the transfer in Wallet; sending the request
  itself never moves funds.

Payment requests are currently ordinary chat text links, not a transaction
receipt or a server-verified payment state. The Messenger backend does not sign,
broadcast, or claim that a request has been paid. Group payment requests are
not exposed in this iteration.

## Security boundary

The Messenger API retains the verified public address and timestamp for a
Wallet link. It never receives a seed phrase, password, private key, or signed
transaction. The Wallet iframe is served from the Wallet's own origin, and its
Messenger embed route has a frame-ancestors allowlist for the Chat domain only.
Untrusted query values are treated as display-only prefill; no transfer is
automatically submitted or signed. Direct navigation and the Wallet's existing
account, backup, activity, and settings screens remain available on the Wallet
domain.

The iframe integration does not provide cross-domain single sign-on. A user
may need to unlock or authenticate Wallet in its own frame. If an iOS browser
blocks required storage or framing behavior, **Open separately** is the
supported fallback.
