# Messenger Wallet Integration — Read Only Phase

The Wallet section is a read-only view of a user-entered public NSAT address.
On desktop it is in the navigation rail. On mobile open **You → Wallet**.

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

## Remaining integration work

- A wallet-origin connection protocol and cryptographic proof that binds the
  Messenger identity to a wallet address are not implemented yet. The current
  public-address lookup is not an account link.
- Cross-domain single sign-on is not implemented. Each application continues
  to authenticate independently.
- Balance and history are shown only after the user enters an address; the
  Messenger identity is not used as proof of wallet ownership.
- Receive QR, wallet selection, send/approve/sign, transaction status cards in
  chat, backup/recovery, and SSO are not enabled in Messenger.
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
