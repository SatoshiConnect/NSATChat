# Offline reading and local media

The PWA shell is precached separately from account data. The offline snapshot makes recent chats readable without treating the server as if it were reachable.

## Behavior

- After a successful sign-in, the app stores a bounded snapshot in IndexedDB, partitioned by account: up to 40 recent rooms, up to 40 recent messages per previously opened room, and up to 500 saved contacts.
- On the next launch, the snapshot can render immediately while the app checks the saved session and refreshes from the server. If the browser reports offline, it opens the local copy directly. A server rejection of the saved session still clears the session and local account cache.
- Offline mode is read-only. The conversation and AI composers are disabled; new messages and AI requests need a connection.
- Same-origin chat photos and profile/room images are cached only when they are images no larger than 2 MB. Cache Storage is capped at 100 objects / 32 MB and entries expire after 21 days. Stories, social media, view-once media, APIs and external media are not cached by the service worker.
- When a chat video preview loads, the app may keep a small poster frame (up to 256 KB; up to 50 per account) so the conversation can show what the clip was while offline.
- Full video files are saved only when the user chooses **Save video offline** in the viewer. Limits are 20 MB per clip, three clips and 40 MB total per account.
- **Settings → Offline data** explains and clears the local snapshot, image cache and video previews/files. Logging out clears this device's offline data too.

## Limits and privacy

Browser storage is best-effort and may be evicted by the browser or device. It is not a backup and must never be used as the source of truth for message delivery, wallet balances, transactions, calls, presence, or social/status visibility. View-once content and private Stories/status media must remain uncached.

Offline snapshots contain recent message text and contact metadata in the browser's IndexedDB. They are account-partitioned and cleared on logout, but IndexedDB is not app-level encryption. Do not put access/refresh tokens or private keys in the snapshot. The app continues to validate the session online before using the server; offline access is only a local read view and cannot learn about remote revocation until reconnection.

This is a bounded offline-reading layer, not full offline sync. Do not queue writes for later delivery without adding explicit idempotency, conflict handling and user-visible delivery state.
