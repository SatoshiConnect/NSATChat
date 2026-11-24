"""Publish a real, sellable marketplace listing from local assets."""

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.marketplace.models import DigitalItem, DigitalItemAsset, MarketplaceAuditEvent
from apps.wallet_integration.models import WalletLink

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class Command(BaseCommand):
    help = (
        "Create a marketplace listing from a folder of images. It stays in review "
        "unless --approve is passed; a listing can only be sold once its creator "
        "has connected an NSAT wallet, and live payments must be enabled."
    )

    def add_arguments(self, parser):
        parser.add_argument("--creator", required=True, help="Phone number of the creator account.")
        parser.add_argument("--title", required=True)
        parser.add_argument("--kind", default="sticker_pack", choices=[choice.value for choice in DigitalItem.Kind])
        parser.add_argument("--price", type=int, required=True, help="Listing price in whole NSAT.")
        parser.add_argument("--assets", help="Folder of sticker images (sticker packs need 1-30).")
        parser.add_argument("--preview", help="Optional preview image path.")
        parser.add_argument("--description", default="")
        parser.add_argument("--rights", default="Personal in-app use.")
        parser.add_argument("--approve", action="store_true", help="Publish immediately instead of queuing review.")

    def handle(self, *args, **options):
        price = options["price"]
        if price <= 0:
            raise CommandError("--price must be greater than 0; free items need no checkout.")
        try:
            creator = User.objects.get(phone_number=options["creator"])
        except User.DoesNotExist:
            raise CommandError("No account with that phone number.")
        if not WalletLink.objects.filter(user=creator).exists():
            self.stderr.write(self.style.WARNING(
                "This creator has not connected an NSAT wallet yet; buyers will see the item as not for sale."
            ))
        asset_paths = []
        if options["assets"]:
            folder = Path(options["assets"]).expanduser()
            if not folder.is_dir():
                raise CommandError("--assets must be a directory.")
            asset_paths = sorted(
                path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            )
        if options["kind"] == "sticker_pack" and not asset_paths:
            raise CommandError("A sticker pack needs at least one image in --assets.")
        if len(asset_paths) > 30:
            raise CommandError("A sticker pack can contain at most 30 images.")
        preview = Path(options["preview"]).expanduser() if options["preview"] else None
        if preview and not preview.is_file():
            raise CommandError("--preview must be an existing image file.")

        state = DigitalItem.State.APPROVED if options["approve"] else DigitalItem.State.PENDING
        with transaction.atomic():
            item = DigitalItem.objects.create(
                creator=creator,
                kind=options["kind"],
                title=options["title"][:100],
                description=options["description"][:1000],
                usage_rights=options["rights"][:500],
                proposed_price_nsat=price,
                state=state,
            )
            if preview:
                with preview.open("rb") as handle:
                    item.preview.save(preview.name, File(handle), save=True)
            for position, path in enumerate(asset_paths):
                with path.open("rb") as handle:
                    asset = DigitalItemAsset(item=item, position=position)
                    asset.image.save(path.name, File(handle), save=True)
                    asset.full_clean()
                    asset.save()
            MarketplaceAuditEvent.objects.create(
                actor=creator,
                item=item,
                action="item.published" if state == DigitalItem.State.APPROVED else "item.submitted",
                metadata={"source": "management_command", "assets": len(asset_paths), "price_nsat": price},
            )
        self.stdout.write(self.style.SUCCESS(
            f"{item.title} (#{item.pk}) {state} with {len(asset_paths)} asset(s) at {price} NSAT."
        ))
