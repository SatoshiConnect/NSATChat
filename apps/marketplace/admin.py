from django.contrib import admin

from .models import CreatorNotification, CreatorProfile, DigitalItem, GiftEvent, InventoryItem, ItemReport, MarketplaceAuditEvent, PurchaseDispute, SimulatedPurchase


@admin.register(DigitalItem)
class DigitalItemAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "creator", "proposed_price_nsat", "state", "created_at")
    list_filter = ("kind", "state")
    search_fields = ("title", "description", "creator__phone_number", "creator__email")
    actions = ("approve_items", "disable_items")

    def save_model(self, request, obj, form, change):
        prior_state = None
        if change:
            prior_state = DigitalItem.objects.filter(pk=obj.pk).values_list("state", flat=True).first()
        super().save_model(request, obj, form, change)
        if prior_state != obj.state:
            MarketplaceAuditEvent.objects.create(actor=request.user, item=obj, action="item.moderation_changed", metadata={"from": prior_state, "to": obj.state})

    @admin.action(description="Approve selected marketplace items")
    def approve_items(self, request, queryset):
        items = list(queryset)
        for item in items:
            item.state = DigitalItem.State.APPROVED
            item.save(update_fields=("state", "updated_at"))
            MarketplaceAuditEvent.objects.create(actor=request.user, item=item, action="item.approved")

    @admin.action(description="Disable selected marketplace items")
    def disable_items(self, request, queryset):
        items = list(queryset)
        for item in items:
            item.state = DigitalItem.State.DISABLED
            item.save(update_fields=("state", "updated_at"))
            MarketplaceAuditEvent.objects.create(actor=request.user, item=item, action="item.disabled")


@admin.register(ItemReport)
class ItemReportAdmin(admin.ModelAdmin):
    list_display = ("item", "reporter", "reason", "state", "created_at")
    list_filter = ("reason", "state")
    actions = ("action_reports", "dismiss_reports")

    def save_model(self, request, obj, form, change):
        old_state = ItemReport.objects.filter(pk=obj.pk).values_list("state", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        if old_state != obj.state:
            MarketplaceAuditEvent.objects.create(actor=request.user, item=obj.item, action="report.moderation_changed", metadata={"report_id": obj.pk, "from": old_state, "to": obj.state})

    @admin.action(description="Mark selected reports actioned and disable items")
    def action_reports(self, request, queryset):
        for report in queryset.select_related("item"):
            report.state = ItemReport.State.ACTIONED
            report.save(update_fields=("state",))
            report.item.state = DigitalItem.State.DISABLED
            report.item.save(update_fields=("state", "updated_at"))
            MarketplaceAuditEvent.objects.create(actor=request.user, item=report.item, action="report.actioned", metadata={"report_id": report.pk})

    @admin.action(description="Dismiss selected reports")
    def dismiss_reports(self, request, queryset):
        for report in queryset.select_related("item"):
            report.state = ItemReport.State.DISMISSED
            report.save(update_fields=("state",))
            MarketplaceAuditEvent.objects.create(actor=request.user, item=report.item, action="report.dismissed", metadata={"report_id": report.pk})


@admin.register(SimulatedPurchase)
class SimulatedPurchaseAdmin(admin.ModelAdmin):
    list_display = ("id", "buyer", "item", "amount_nsat", "state", "simulation_only", "created_at")
    readonly_fields = ("id", "buyer", "item", "idempotency_key", "amount_nsat", "state", "simulation_only", "created_at")


admin.site.register(InventoryItem)


@admin.register(MarketplaceAuditEvent)
class MarketplaceAuditEventAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "item", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("action", "actor__phone_number", "actor__email", "item__title")
    readonly_fields = ("actor", "item", "action", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreatorProfile)
class CreatorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "is_public", "created_at")
    search_fields = ("user__phone_number", "user__email", "display_name")
    list_filter = ("is_public",)


@admin.register(PurchaseDispute)
class PurchaseDisputeAdmin(admin.ModelAdmin):
    list_display = ("purchase", "buyer", "state", "simulation_only", "created_at")
    list_filter = ("state",)
    actions = ("dismiss_disputes",)
    readonly_fields = ("purchase", "buyer", "reason", "simulation_only", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        old_state = PurchaseDispute.objects.filter(pk=obj.pk).values_list("state", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        if old_state != obj.state:
            MarketplaceAuditEvent.objects.create(actor=request.user, item=obj.purchase.item, action="purchase.dispute_moderated", metadata={"purchase_id": str(obj.purchase_id), "from": old_state, "to": obj.state})

    @admin.action(description="Dismiss selected simulated disputes")
    def dismiss_disputes(self, request, queryset):
        for dispute in queryset.select_related("purchase__item"):
            old_state = dispute.state
            dispute.state = PurchaseDispute.State.DISMISSED
            dispute.save(update_fields=("state", "updated_at"))
            MarketplaceAuditEvent.objects.create(actor=request.user, item=dispute.purchase.item, action="purchase.dispute_moderated", metadata={"purchase_id": str(dispute.purchase_id), "from": old_state, "to": dispute.state})


admin.site.register(CreatorNotification)


@admin.register(GiftEvent)
class GiftEventAdmin(admin.ModelAdmin):
    list_display = ("item", "sender", "recipient", "simulation_only", "created_at")
    readonly_fields = ("sender", "recipient", "item", "status", "simulation_only", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
