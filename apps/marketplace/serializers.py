from rest_framework import serializers

from . import services
from .models import (
    CreatorProfile,
    DigitalItem,
    DigitalItemAsset,
    GiftEvent,
    InventoryItem,
    ItemReport,
    MarketplaceEntitlement,
    SimulatedPurchase,
)


class DigitalItemSerializer(serializers.ModelSerializer):
    creator_name = serializers.SerializerMethodField()
    price_label = serializers.SerializerMethodField()
    sticker_count = serializers.SerializerMethodField()
    purchase_mode = serializers.SerializerMethodField()

    class Meta:
        model = DigitalItem
        fields = ("id", "kind", "title", "description", "preview", "proposed_price_nsat", "price_label", "usage_rights", "creator_name", "state", "created_at", "sticker_count", "purchase_mode")

    def get_purchase_mode(self, obj):
        """nsat: payable now. simulation: demo only. closed: not for sale."""
        if obj.pk in self.context.get("owned_ids", ()):  # paid or granted already
            return "owned"
        if not obj.creator_id or not obj.proposed_price_nsat:
            return "closed"
        try:
            mode = services.purchase_mode()
            services.platform_fee_bps()
        except services.MarketplaceError:
            return "closed"
        link = getattr(obj.creator, "nsat_wallet_link", None)
        if mode == "nsat" and not (link and link.address):
            # A listing whose creator has not connected a wallet cannot settle.
            return "closed"
        return mode

    def get_creator_name(self, obj):
        if not obj.creator_id:
            return "SatoshiCore Studio"
        try:
            display_name = obj.creator.creator_profile.display_name
            if display_name:
                return display_name
        except AttributeError:
            pass
        try:
            return obj.creator.profile.display_name or "SatoshiCore creator"
        except AttributeError:
            return "SatoshiCore creator"

    def get_price_label(self, obj):
        return "Free" if not obj.proposed_price_nsat else f"{obj.proposed_price_nsat:,} NSAT"

    def get_sticker_count(self, obj):
        return obj.assets.count() if obj.kind == DigitalItem.Kind.STICKER_PACK else 0


class OwnedStickerAssetSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = DigitalItemAsset
        fields = ("id", "file", "position")

    def get_file(self, obj):
        request = self.context.get("request")
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class OwnedStickerPackSerializer(serializers.ModelSerializer):
    stickers = OwnedStickerAssetSerializer(source="assets", many=True, read_only=True)

    class Meta:
        model = DigitalItem
        fields = ("id", "title", "description", "preview", "stickers")


class SubmitItemSerializer(serializers.ModelSerializer):
    assets = serializers.ListField(
        child=serializers.ImageField(), required=False, write_only=True, allow_empty=True,
    )

    class Meta:
        model = DigitalItem
        fields = ("id", "kind", "title", "description", "preview", "assets", "proposed_price_nsat", "usage_rights", "state", "created_at")
        read_only_fields = ("id", "state", "created_at")
        extra_kwargs = {"description": {"required": False}, "usage_rights": {"required": False}}

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A title is required.")
        return value

    def validate_proposed_price_nsat(self, value):
        if value > 1_000_000_000:
            raise serializers.ValidationError("The proposed price cannot exceed 1,000,000,000 NSAT.")
        return value

    def validate_preview(self, value):
        if value:
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("Preview must be 5 MB or smaller.")
            if value.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                raise serializers.ValidationError("Use a JPEG, PNG, WebP, or GIF preview.")
        return value

    def validate_assets(self, files):
        if len(files) > 30:
            raise serializers.ValidationError("A sticker pack can contain at most 30 images.")
        for image in files:
            if image.size > 2 * 1024 * 1024:
                raise serializers.ValidationError("Each sticker must be 2 MB or smaller.")
        return files

    def validate(self, attrs):
        kind = attrs.get("kind")
        assets = attrs.get("assets", [])
        if kind == DigitalItem.Kind.STICKER_PACK and not assets:
            raise serializers.ValidationError({"assets": "Add at least one sticker image to submit a sticker pack."})
        if kind != DigitalItem.Kind.STICKER_PACK and assets:
            raise serializers.ValidationError({"assets": "Sticker images can only be added to a sticker pack."})
        return attrs

    def create(self, validated_data):
        assets = validated_data.pop("assets", [])
        item = super().create(validated_data)
        DigitalItemAsset.objects.bulk_create([
            DigitalItemAsset(item=item, image=image, position=position)
            for position, image in enumerate(assets)
        ])
        return item


class InventorySerializer(serializers.ModelSerializer):
    item = DigitalItemSerializer(read_only=True)

    class Meta:
        model = InventoryItem
        fields = ("id", "item", "acquired_at")


class GiftEventSerializer(serializers.ModelSerializer):
    item = DigitalItemSerializer(read_only=True)

    class Meta:
        model = GiftEvent
        fields = ("id", "item", "created_at", "simulation_only")


class ItemReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemReport
        fields = ("reason", "details")


class CreatorProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreatorProfile
        fields = ("display_name", "bio", "is_public")

    def validate_display_name(self, value):
        return value.strip()


class SimulatedPurchaseSerializer(serializers.ModelSerializer):
    item = DigitalItemSerializer(read_only=True)
    dispute_state = serializers.SerializerMethodField()

    class Meta:
        model = SimulatedPurchase
        fields = ("id", "item", "amount_nsat", "state", "simulation_only", "created_at", "dispute_state")

    def get_dispute_state(self, obj):
        try:
            return obj.dispute.state
        except AttributeError:
            return ""


class EntitlementSerializer(serializers.ModelSerializer):
    item = DigitalItemSerializer(read_only=True)
    order_id = serializers.CharField(read_only=True)

    class Meta:
        model = MarketplaceEntitlement
        fields = ("id", "item", "order_id", "acquired_at", "revoked_at")
