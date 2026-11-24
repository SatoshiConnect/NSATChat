from django.contrib import admin
from django.db import transaction
from django.utils import timezone

from .models import (
    Status,
    StatusView,
    StatusReport,
)


@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "user",
        "status_type",
        "created_at",
        "expires_at",
        "is_deleted",
    )

    list_filter = (
        "status_type",
        "is_deleted",
    )

    search_fields = (
        "user__phone_number",
        "content",
    )


@admin.register(StatusView)
class StatusViewAdmin(admin.ModelAdmin):

    list_display = (
        "status",
        "viewer",
        "viewed_at",
    )

    search_fields = (
        "viewer__phone_number",
    )


@admin.register(StatusReport)
class StatusReportAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "reporter", "reason", "state", "created_at", "reviewed_by")
    list_filter = ("state", "reason", "created_at")
    search_fields = ("status__content", "status__user__phone_number", "reporter__phone_number", "details")
    readonly_fields = ("status", "reporter", "reason", "details", "created_at", "reviewed_at", "reviewed_by")
    actions = ("mark_reviewed", "hide_reported_statuses")

    @admin.action(description="Mark selected reports as reviewed")
    def mark_reviewed(self, request, queryset):
        reviewed_at = timezone.now()
        with transaction.atomic():
            for report in queryset.select_related("status"):
                report.state = StatusReport.REVIEWED
                report.reviewed_by = request.user
                report.reviewed_at = reviewed_at
                report.save(update_fields=("state", "reviewed_by", "reviewed_at"))
                self.log_change(request, report, "Marked status report as reviewed.")

    @admin.action(description="Hide reported statuses and remove their media")
    def hide_reported_statuses(self, request, queryset):
        reviewed_at = timezone.now()
        with transaction.atomic():
            reports = list(queryset.select_related("status").order_by("id"))
            status_ids = {report.status_id for report in reports}
            for story in Status.objects.filter(pk__in=status_ids):
                if not story.is_deleted:
                    media = story.media
                    story.is_deleted = True
                    story.save(update_fields=("is_deleted",))
                    if media:
                        media.delete(save=False)
                    self.log_change(request, story, "Hidden by a moderator after a status report.")
                    from .utils import notify_status_feed_changed
                    transaction.on_commit(lambda owner=story.user: notify_status_feed_changed(owner, "moderated"))
            for report in reports:
                report.state = StatusReport.ACTIONED
                report.reviewed_by = request.user
                report.reviewed_at = reviewed_at
                report.save(update_fields=("state", "reviewed_by", "reviewed_at"))
                self.log_change(request, report, "Took moderation action and hid the status.")
