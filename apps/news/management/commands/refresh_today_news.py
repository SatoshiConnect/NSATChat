from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.news.views import (
    FRESH_CACHE_KEY,
    FRESH_TTL_SECONDS,
    STALE_CACHE_KEY,
    STALE_TTL_SECONDS,
    _fetch_today_items,
)


class Command(BaseCommand):
    help = "Refresh the cached Today news feed from its configured publishers."

    def handle(self, *args, **options):
        lock_key = f"{FRESH_CACHE_KEY}:refresh-lock"
        if not cache.add(lock_key, "1", timeout=60):
            self.stdout.write("Today news refresh is already running; skipped.")
            return

        try:
            try:
                feed = _fetch_today_items()
            except Exception as exc:
                # Leave the previous stale feed available if publishers are down.
                raise CommandError("Today news refresh failed; cached news was preserved.") from exc

            cache.set(FRESH_CACHE_KEY, feed, FRESH_TTL_SECONDS)
            cache.set(STALE_CACHE_KEY, feed, STALE_TTL_SECONDS)
            image_count = sum(bool(item.get("image_url")) for item in feed.get("items", []))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Today news refreshed: {len(feed.get('items', []))} stories, "
                    f"{image_count} with images, {len(feed.get('sources', []))} sources."
                )
            )
        finally:
            cache.delete(lock_key)
