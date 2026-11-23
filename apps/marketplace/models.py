import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class DigitalItem(models.Model):
    class Kind(models.TextChoices):
        GIFT = "gift", "Creator gift"
        STICKER_PACK = "sticker_pack", "Sticker pack"
        PROFILE_FRAME = "profile_frame", "Profile frame"
        BADGE = "badge", "Badge"
        THEME = "theme", "Theme"
        AVATAR = "avatar", "Avatar accessory"
        PIXEL_WORLD = "pixel_world", "Pixel World item"

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        DISABLED = "disabled", "Disabled"

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="marketplace_items")
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=1000, blank=True)
    preview = models.ImageField(upload_to="marketplace/previews/", blank=True)
    proposed_price_nsat = models.PositiveBigIntegerField(default=0, help_text="Display-only proposed price; not charged.")
    usage_rights = models.CharField(max_length=500, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING, db_index=True)
    moderation_note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("state", "kind", "created_at"), name="mkt_state_kind_created")]

    def clean(self):
        super().clean()
        if self.preview and self.preview.size > 5 * 1024 * 1024:
            raise ValidationError({"preview": "Preview must be 5 MB or smaller."})

    def __str__(self):
        return self.title


class DigitalItemAsset(models.Model):
    """User-created content belonging to a moderated digital item."""

    item = models.ForeignKey(DigitalItem, on_delete=models.CASCADE, related_name="assets")
    image = models.ImageField(upload_to="marketplace/assets/")
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("position", "id")
        constraints = [
            models.UniqueConstraint(fields=("item", "position"), name="marketplace_asset_item_position"),
        ]

    def clean(self):
        super().clean()
        if self.image and self.image.size > 2 * 1024 * 1024:
            raise ValidationError({"image": "Each sticker must be 2 MB or smaller."})

    def __str__(self):
        return f"{self.item.title} asset {self.position + 1}"


class SimulatedPurchase(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", "Pending simulation"
        CONFIRMED = "confirmed", "Simulation confirmed"
        FAILED = "failed", "Simulation failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_simulated_purchases")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="simulated_purchases")
    idempotency_key = models.UUIDField()
    amount_nsat = models.PositiveBigIntegerField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.CONFIRMED)
    simulation_only = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("buyer", "idempotency_key"), name="marketplace_purchase_idempotency")]
        ordering = ("-created_at",)


class InventoryItem(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_inventory")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="inventory_entries")
    purchase = models.OneToOneField(SimulatedPurchase, on_delete=models.CASCADE, related_name="inventory_entry")
    acquired_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("owner", "item", "purchase"), name="marketplace_inventory_unique")]


class GiftEvent(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_gifts_sent")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_gifts_received")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="gift_events")
    status = models.ForeignKey("status.Status", on_delete=models.SET_NULL, null=True, blank=True, related_name="creator_gifts")
    simulation_only = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ItemReport(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed"
        DISMISSED = "dismissed", "Dismissed"
        ACTIONED = "actioned", "Actioned"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_reports")
    item = models.ForeignKey(DigitalItem, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=32, choices=(("copyright", "Copyright"), ("unsafe", "Unsafe"), ("spam", "Spam"), ("other", "Other")))
    details = models.CharField(max_length=1000, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MarketplaceAuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    item = models.ForeignKey(DigitalItem, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class CreatorNotification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="creator_notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="creator_actions")
    item = models.ForeignKey(DigitalItem, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=32)
    message = models.CharField(max_length=200)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class CreatorProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="creator_profile")
    display_name = models.CharField(max_length=80, blank=True)
    bio = models.CharField(max_length=500, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PurchaseDispute(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        REVIEWED = "reviewed", "Reviewed"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    purchase = models.OneToOneField(SimulatedPurchase, on_delete=models.CASCADE, related_name="dispute")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_disputes")
    reason = models.CharField(max_length=500)
    state = models.CharField(max_length=12, choices=State.choices, default=State.OPEN, db_index=True)
    simulation_only = models.BooleanField(default=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
