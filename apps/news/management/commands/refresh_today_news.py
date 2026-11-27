from django.core.management.base import BaseCommand, CommandError

from apps.news.views import refresh_today_cache


class Command(BaseCommand):
    help = "Refresh the cached public news and video feed."

    def handle(self, *args, **options):
        try:
            feed = refresh_today_cache()
        except Exception as exc:
            raise CommandError("News refresh failed; the last cached feed remains available.") from exc
        video_count = sum(1 for item in feed.get("items", []) if item.get("media_type") == "VIDEO")
        image_count = sum(1 for item in feed.get("items", []) if item.get("image_url"))
        self.stdout.write(self.style.SUCCESS(
            f"News cache refreshed: {len(feed.get('items', []))} current items, "
            f"{image_count} with images, {video_count} videos."
        ))
