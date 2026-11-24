"""Remove expired stories and their media, retaining stories saved as highlights."""

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.status.models import Status


BATCH_SIZE = 500


def purge_expired_statuses(now=None, batch_size=BATCH_SIZE):
    """Delete expired, non-highlighted statuses and unreferenced media files."""
    now = now or timezone.now()
    deleted = 0

    while True:
        ids = list(
            Status.objects.filter(expires_at__lte=now)
            .exclude(highlight_items__isnull=False)
            .order_by("id")
            .values_list("id", flat=True)[:batch_size]
        )
        if not ids:
            break

        with transaction.atomic():
            stories = list(Status.objects.select_for_update().filter(pk__in=ids))
            removable_ids = [story.id for story in stories]
            media_names = {story.media.name for story in stories if story.media}
            if removable_ids:
                Status.objects.filter(pk__in=removable_ids).delete()

        for name in media_names:
            # A storage key may be referenced by another row; preserve it until
            # the final reference is gone. delete() is idempotent for missing files.
            if not Status.objects.filter(media=name).exists():
                default_storage.delete(name)

        deleted += len(removable_ids)
        if len(ids) < batch_size:
            break

    return deleted


class Command(BaseCommand):
    help = "Delete expired status rows and media while preserving highlighted stories."

    def handle(self, *args, **options):
        deleted = purge_expired_statuses()
        self.stdout.write(f"Deleted {deleted} expired status(es).")
