from django.contrib import admin

from .models import (
    AssistantControl,
    AssistantUsage,
    Attachment,
    ChatRoom,
    Message,
    Participant,
    OpenCommunity,
    OpenCommunityReport,
)
from django.db.models import Sum
from django.utils import timezone


# =============================================================================
# Inlines
# =============================================================================

class ParticipantInline(admin.TabularInline):
    """
    Inline admin for chat participants.
    """

    model = Participant
    extra = 0

    autocomplete_fields = (
        "user",
    )

    readonly_fields = (
        "joined_at",
    )

    show_change_link = True


class AttachmentInline(admin.TabularInline):
    """
    Inline admin for message attachments.
    """

    model = Attachment
    extra = 0

    readonly_fields = (
        "file_name",
        "file_size",
        "mime_type",
        "uploaded_at",
    )

    show_change_link = True


@admin.register(AssistantControl)
class AssistantControlAdmin(admin.ModelAdmin):
    list_display = ("image_generation_enabled", "image_daily_quota", "monthly_budget_usd", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not AssistantControl.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AssistantUsage)
class AssistantUsageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "task", "model_id", "status", "input_tokens", "output_tokens", "image_count", "estimated_cost_usd")
    list_filter = ("task", "status", "created_at", "model_id")
    search_fields = ("user__phone_number", "user__public_id", "model_id")
    readonly_fields = tuple(field.name for field in AssistantUsage._meta.fields)
    date_hierarchy = "created_at"
    list_per_page = 50

    def changelist_view(self, request, extra_context=None):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        extra_context = extra_context or {}
        extra_context["ai_usage_today"] = AssistantUsage.objects.filter(status="OK", created_at__date=today).aggregate(total=Sum("estimated_cost_usd"))["total"] or 0
        extra_context["ai_usage_month"] = AssistantUsage.objects.filter(status__in=("OK", "PENDING"), created_at__date__gte=month_start).aggregate(total=Sum("estimated_cost_usd"))["total"] or 0
        return super().changelist_view(request, extra_context=extra_context)


# =============================================================================
# Chat Room
# =============================================================================

@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    """
    Admin configuration for ChatRoom.
    """

    inlines = (
        ParticipantInline,
    )

    list_display = (
        "id",
        "name",
        "room_type",
        "created_by",
        "is_active",
        "created_at",
    )

    list_display_links = (
        "id",
        "name",
    )

    list_editable = (
        "is_active",
    )

    list_filter = (
        "room_type",
        "is_active",
        "created_at",
    )

    search_fields = (
        "name",
        "description",
        "created_by__phone_number",
    )

    autocomplete_fields = (
        "created_by",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "created_by",
    )

    ordering = (
        "-updated_at",
    )

    list_per_page = 25

    date_hierarchy = "created_at"

    show_full_result_count = True

    empty_value_display = "-"

    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "room_type",
                    "created_by",
                ),
            },
        ),
        (
            "Group Information",
            {
                "classes": ("collapse",),
                "fields": (
                    "description",
                    "photo",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_active",
                ),
            },
        ),
        (
            "Important Dates",
            {
                "classes": ("collapse",),
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )


# =============================================================================
# Participant
# =============================================================================

@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    """
    Admin configuration for Participant.
    """

    list_display = (
        "id",
        "room",
        "user",
        "is_admin",
        "is_muted",
        "is_archived",
        "joined_at",
    )

    list_display_links = (
        "id",
        "user",
    )

    list_editable = (
        "is_admin",
        "is_muted",
        "is_archived",
    )

    list_filter = (
        "is_admin",
        "is_muted",
        "is_archived",
        "joined_at",
    )

    search_fields = (
        "user__phone_number",
        "room__name",
    )

    autocomplete_fields = (
        "room",
        "user",
    )

    readonly_fields = (
        "joined_at",
    )

    list_select_related = (
        "room",
        "user",
    )

    ordering = (
        "-joined_at",
    )

    list_per_page = 25

    date_hierarchy = "joined_at"

    empty_value_display = "-"

    fieldsets = (
        (
            "Participant",
            {
                "fields": (
                    "room",
                    "user",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_admin",
                    "is_muted",
                    "is_archived",
                ),
            },
        ),
        (
            "Important Dates",
            {
                "fields": (
                    "joined_at",
                ),
            },
        ),
    )


# =============================================================================
# Message
# =============================================================================

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """
    Admin configuration for Message.
    """

    inlines = (
        AttachmentInline,
    )

    list_display = (
        "id",
        "sender",
        "room",
        "message_type",
        "is_edited",
        "is_deleted",
        "created_at",
    )

    list_display_links = (
        "id",
        "sender",
    )

    list_editable = (
        "is_deleted",
    )

    list_filter = (
        "message_type",
        "is_deleted",
        "is_edited",
        "created_at",
    )

    search_fields = (
        "content",
        "sender__phone_number",
        "room__name",
    )

    autocomplete_fields = (
        "room",
        "sender",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    list_select_related = (
        "room",
        "sender",
    )

    ordering = (
        "-created_at",
    )

    list_per_page = 50

    date_hierarchy = "created_at"

    empty_value_display = "-"

    fieldsets = (
        (
            "Message",
            {
                "fields": (
                    "room",
                    "sender",
                    "message_type",
                    "content",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "is_edited",
                    "is_deleted",
                ),
            },
        ),
        (
            "Important Dates",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )


# =============================================================================
# Attachment
# =============================================================================

@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    """
    Admin configuration for Attachment.
    """

    list_display = (
        "id",
        "message",
        "file_name",
        "file_size",
        "mime_type",
        "uploaded_at",
    )

    list_display_links = (
        "id",
        "file_name",
    )

    list_filter = (
        "mime_type",
        "uploaded_at",
    )

    search_fields = (
        "file_name",
        "message__content",
    )

    autocomplete_fields = (
        "message",
    )

    readonly_fields = (
        "file_name",
        "file_size",
        "mime_type",
        "uploaded_at",
    )

    list_select_related = (
        "message",
    )

    ordering = (
        "-uploaded_at",
    )

    list_per_page = 25

    date_hierarchy = "uploaded_at"

    empty_value_display = "-"

# Per-user chat clear markers are useful for support/debugging.
from apps.chat.models import ChatClear

@admin.register(ChatClear)
class ChatClearAdmin(admin.ModelAdmin):
    list_display = ("room", "user", "cleared_at")
    list_filter = ("cleared_at",)
    search_fields = ("user__phone_number", "room__name")


@admin.register(OpenCommunity)
class OpenCommunityAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "owner", "category", "join_mode", "state", "searchable", "created_at")
    list_filter = ("state", "category", "join_mode", "searchable", "created_at")
    search_fields = ("room__name", "room__description", "owner__phone_number")
    readonly_fields = ("created_at", "updated_at", "published_at", "join_code_hash")
    actions = ("publish_communities", "suspend_communities")

    @admin.action(description="Approve and publish selected communities")
    def publish_communities(self, request, queryset):
        for community in queryset.exclude(state=OpenCommunity.State.PUBLISHED):
            community.publish()
            self.log_change(request, community, "Approved and published after moderation review.")

    @admin.action(description="Suspend selected communities from discovery")
    def suspend_communities(self, request, queryset):
        for community in queryset.exclude(state=OpenCommunity.State.SUSPENDED):
            community.state = OpenCommunity.State.SUSPENDED
            community.save(update_fields=("state", "updated_at"))
            self.log_change(request, community, "Suspended from OpenChat discovery.")


@admin.register(OpenCommunityReport)
class OpenCommunityReportAdmin(admin.ModelAdmin):
    list_display = ("id", "community", "reporter", "reason", "state", "created_at", "reviewed_by")
    list_filter = ("state", "reason", "created_at")
    search_fields = ("community__room__name", "reporter__phone_number", "details")
    readonly_fields = ("community", "reporter", "reason", "details", "created_at")
    def save_model(self, request, obj, form, change):
        if change and "state" in form.changed_data:
            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
        super().save_model(request, obj, form, change)
