# Persistent social posts — phase 1

This module is separate from `apps.status`: Stories remain ephemeral and expire after 24 hours; social posts are durable until deleted by their author.

## Included

- Authenticated text and image posts (JPEG, PNG, WebP, GIF; 8 MiB maximum).
- Per-post audience choice: `CONTACTS` or `EVERYONE`.
- Server-enforced visibility. Contact posts are visible to users the author has saved; blocked accounts are excluded in either direction.
- Feed paging (20 items by default, 50 maximum), likes, bounded recent comments, and author deletion.
- No content ranking, reposting, follower graph, moderation queue, or public discovery controls are included in this phase.

## API

- `GET/POST /api/social/posts/`
- `POST/DELETE /api/social/posts/{id}/` (toggle like / author soft-delete)
- `GET/POST /api/social/posts/{id}/comments/`

All routes require an authenticated Messenger session. The client must treat the feed as untrusted user content; rendering uses React text nodes, not HTML.

## Follow-up before calling the social product complete

Add post reporting and moderation, comment deletion/editing, audience/privacy preferences, notifications, upload malware/content scanning, and device-level responsive review. Decide whether comments are allowed for public posts from non-contacts, and add account-level feed/discovery controls. This phase does not implement follower feeds, ranking, reposting, or Stories-to-post conversion.
