from rest_framework import serializers

from .models import CreatorProfile, DigitalItem, GiftEvent, InventoryItem, ItemReport, SimulatedPurchase


class DigitalItemSerializer(serializers.ModelSerializer):
    creator_name = serializers.SerializerMethodField()
    price_label = serializers.SerializerMethodField()

    class Meta:
        model = DigitalItem
        fields = ("id", "kind", "title", "description", "preview", "proposed_price_nsat", "price_label", "usage_rights", "creator_name", "state", "created_at")

    def get_creator_name(self, obj):
        if not obj.creator_id:
            return "SatoshiCore Studio"
        try:
            return obj.creator.profile.display_name or "SatoshiCore creator"
        except AttributeError:
            return "SatoshiCore creator"

    def get_price_label(self, obj):
        return "Free" if not obj.proposed_price_nsat else f"{obj.proposed_price_nsat:,} NSAT proposed"


class SubmitItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DigitalItem
        fields = ("id", "kind", "title", "description", "preview", "proposed_price_nsat", "usage_rights", "state", "created_at")
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
