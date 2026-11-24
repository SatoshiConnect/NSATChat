import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


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


class MarketplaceOrder(models.Model):
    """A priced purchase that settles in NSAT through signed wallets.

    Each order snapshots its split and payees so a later settings change cannot
    re-price an order the buyer is already paying. Settlement only completes
    after the indexer confirms every required payment.
    """

    class State(models.TextChoices):
        AWAITING_PAYMENT = "awaiting_payment", "Awaiting payment"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_orders")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="orders")
    idempotency_key = models.UUIDField()
    unit_amount_nsat = models.PositiveBigIntegerField()
    platform_fee_bps = models.PositiveSmallIntegerField(default=0)
    platform_fee_nsat = models.PositiveBigIntegerField(default=0)
    creator_proceeds_nsat = models.PositiveBigIntegerField()
    network = models.CharField(max_length=64)
    treasury_address = models.CharField(max_length=56, blank=True, default="")
    state = models.CharField(max_length=20, choices=State.choices, default=State.AWAITING_PAYMENT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "marketplace_orders"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("buyer", "idempotency_key"), name="marketplace_order_idempotency"),
        ]
        indexes = [models.Index(fields=("state", "expires_at"), name="mkt_order_state_exp")]

    @property
    def total_due_nsat(self):
        return self.creator_proceeds_nsat + self.platform_fee_nsat

    def __str__(self):
        return f"{self.item_id} order {self.id}"


class OrderPayment(models.Model):
    """One required transfer of an order: the creator share or the platform fee."""

    class Role(models.TextChoices):
        CREATOR = "creator", "Creator share"
        PLATFORM = "platform", "Platform fee"

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        FAILED = "failed", "Failed"

    order = models.ForeignKey(MarketplaceOrder, on_delete=models.CASCADE, related_name="payments")
    role = models.CharField(max_length=16, choices=Role.choices)
    payee_address = models.CharField(max_length=56)
    amount_nsat = models.PositiveBigIntegerField()
    tx_hash = models.CharField(max_length=64, blank=True, default="")
    submitted_at = models.BigIntegerField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    ledger = models.BigIntegerField(null=True, blank=True)
    # When reconciliation last re-read this transfer on chain. Reorg re-checks
    # take the least recently verified rows first, so every confirmed transfer
    # in the window is revisited instead of only the newest ones.
    chain_checked_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.PENDING, db_index=True)

    class Meta:
        db_table = "marketplace_order_payments"
        ordering = ("role",)
        constraints = [
            models.UniqueConstraint(fields=("order", "role"), name="marketplace_order_payment_role"),
            models.UniqueConstraint(
                fields=("tx_hash",),
                condition=~models.Q(tx_hash=""),
                name="marketplace_order_payment_tx",
            ),
        ]

    def __str__(self):
        return f"{self.order_id} {self.role}"


class MarketplaceEntitlement(models.Model):
    """Ownership granted only after a confirmed order.

    A paid entitlement is independent of the listing's sale state: disabling an
    item stops new sales but must not take away what a buyer already paid for.
    Access ends only through an explicit, audited revocation.
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_entitlements")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="entitlements")
    order = models.OneToOneField(MarketplaceOrder, on_delete=models.CASCADE, related_name="entitlement")
    acquired_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_reason = models.CharField(max_length=300, blank=True, default="")
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_entitlement_revocations",
    )

    class Meta:
        db_table = "marketplace_entitlements"
        ordering = ("-acquired_at",)
        constraints = [
            models.UniqueConstraint(fields=("owner", "item"), name="marketplace_entitlement_unique"),
        ]

    def __str__(self):
        return f"{self.owner_id} owns {self.item_id}"


class CreatorSale(models.Model):
    """Settlement record creators see when reconciling payouts.

    It must outlive the buyer's account: financial history cannot disappear
    because a customer deleted their profile. The order link therefore goes
    null on deletion while the immutable references and amounts stay.
    """

    order = models.OneToOneField(
        MarketplaceOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creator_sale",
    )
    order_reference = models.UUIDField(null=True, blank=True, db_index=True)
    buyer_reference = models.CharField(max_length=64, blank=True, default="")
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_sales")
    item = models.ForeignKey(DigitalItem, on_delete=models.PROTECT, related_name="creator_sales")
    gross_nsat = models.PositiveBigIntegerField()
    platform_fee_nsat = models.PositiveBigIntegerField(default=0)
    creator_proceeds_nsat = models.PositiveBigIntegerField()
    tx_hash = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "marketplace_creator_sales"
        ordering = ("-created_at",)


class MarketplaceReconciliationRun(models.Model):
    """One audit pass comparing the NSAT chain with the settlement ledger.

    The run is the report admins read: what was scanned, what disagreed and
    what the pass was allowed to repair. A run is never edited after it ends.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        COMMAND = "command", "Scheduled command"
        ADMIN = "admin", "Admin action"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING, db_index=True)
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.COMMAND)
    dry_run = models.BooleanField(default=False)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_reconciliation_runs",
    )
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    orders_scanned = models.PositiveIntegerField(default=0)
    payments_scanned = models.PositiveIntegerField(default=0)
    chain_checks = models.PositiveIntegerField(default=0)
    issues_found = models.PositiveIntegerField(default=0)
    critical_issues = models.PositiveIntegerField(default=0)
    repairs_applied = models.PositiveIntegerField(default=0)
    summary = models.CharField(max_length=300, blank=True, default="")
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "marketplace_reconciliation_runs"
        ordering = ("-started_at",)

    def __str__(self):
        return f"reconciliation {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class MarketplaceReconciliationIssue(models.Model):
    """One disagreement found by a run, kept so admins can filter and follow up.

    The order reference is copied because an order disappears when its buyer
    deletes their account, and a reconciliation report must still make sense.
    """

    class Severity(models.TextChoices):
        CRITICAL = "critical", "Critical"
        WARNING = "warning", "Warning"

    run = models.ForeignKey(MarketplaceReconciliationRun, on_delete=models.CASCADE, related_name="issues")
    code = models.CharField(max_length=48, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    order = models.ForeignKey(
        MarketplaceOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    order_reference = models.UUIDField(null=True, blank=True, db_index=True)
    payment = models.ForeignKey(
        OrderPayment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_issues",
    )
    detail = models.CharField(max_length=300, blank=True, default="")
    repaired = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "marketplace_reconciliation_issues"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("run", "code"), name="mkt_recon_run_code")]

    def __str__(self):
        return f"{self.code} ({self.severity})"
