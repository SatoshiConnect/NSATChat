# Messenger and Wallet Integration

Messenger keeps chat and Wallet as separate products. The Wallet section in
Messenger can read public NSAT account data; signing and transfers stay in
`wallet.satoshicore.org`. On desktop it is in the navigation rail. On mobile
open **You → Wallet**.

## Moving between apps

- From Messenger, open **Wallet** to view a public NSAT address, balance and
  indexed activity, or use **Open SatoshiCore Wallet** for wallet management.
- From SatoshiCore Wallet, use **Messenger** in the site navigation to open
  `https://chat.satoshicore.org/` in a separate tab. The wallet stays open.
- Both entry points use the same official SatoshiCore domains. They do not
  share browser sessions or imply that a wallet address belongs to the signed
  in Messenger account.

## Data flow

1. The browser submits an address to the authenticated Messenger API at
   `GET /api/accounts/wallet/read/`.
2. Django validates the address format and rate limits reads to 30 per user per
   minute.
3. Django verifies the exact NSAT Mainnet identity and reads `balance128` from
   `https://gateway.satoshicore.org`.
4. Recent history is fetched from the fixed first-party indexer at
   `https://satoshicore.org` and filtered to the fields the UI needs.
5. The address is kept in browser `localStorage` only. Messenger does not save
   the submitted address to its database. Since the request passes through
   Messenger, its server can associate the requested public address with the
   authenticated Messenger account; the UI discloses that behavior.

The API is read-only. It does not create an account, prove address ownership,
sign, broadcast, or otherwise submit a transaction. An absent account is
reported as not found; it is never rendered as a zero balance. Amounts stay as
integer strings to avoid floating-point loss.

## Wallet ownership link

The Wallet section can start an authenticated, five-minute one-time challenge.
The user is sent to `wallet.satoshicore.org`, selects a locally saved wallet,
and explicitly unlocks it to sign the exact `chat.satoshicore.org` challenge.
The signature is returned in the URL fragment (not sent to HTTP access logs),
then immediately removed from browser history and verified by the Messenger
server against the public NSAT address. The server stores only the verified
public address and timestamp; it never receives or stores a seed, password, or
private key. Disconnect removes the link. This link proves address control at
the time of signing; it does not grant spending permission.

In a one-to-one chat, **Pay with NSAT** resolves the other participant's
verified wallet address through an authenticated room-scoped endpoint, then
opens the Wallet's existing send screen with that recipient filled in. The
sender chooses the amount and reviews the live fee/network in Wallet before
unlocking and signing. Messenger never receives key material and does not
construct or broadcast a transaction.

## Remaining integration work

- Payment requests, automatic transaction receipts inside the chat, and group
  payments are not implemented yet. A send started from a private chat is
  completed and verified on the Wallet screen.
- Cross-domain single sign-on is not implemented. Each application continues
  to authenticate independently.
- The read-only balance panel still accepts a watch address separately. If no
  watch address is saved, it uses the linked address as its initial read target.
- Receive QR and transaction status cards in chat are not implemented.
- Wallet selection, send/approve/sign, backup/recovery, and SSO remain in the
  Wallet application rather than Messenger.
- Transaction signing and broadcasting remain on `wallet.satoshicore.org`.
  Do not add those operations to Messenger until the cross-origin protocol has
  a security review and the owner separately authorizes real transaction
  support.

## Server behavior

The proxy targets are constants in `apps/wallet_integration/views.py`; the client
cannot provide a URL. The endpoint rejects malformed addresses, checks the
complete expected Mainnet identity before reading an account, requires an
exact decimal-string balance, caps the response size and returns a safe subset
of the indexer response. If the indexer is unavailable, the balance can still
be shown while history is marked unavailable.

The Messenger production server must have outbound HTTPS access to the Gateway
and indexer. No new secret or database migration is required.
