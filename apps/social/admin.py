from django.contrib import admin
from django.utils import timezone
from .models import Post, PostAttachment, PostComment, PostLike, PostReport, PostSave, SocialFollow


class PostCommentInline(admin.TabularInline):
    model = PostComment
    extra = 0
    readonly_fields = ("author", "text", "created_at", "deleted_at")


class PostAttachmentInline(admin.TabularInline):
    model = PostAttachment
    extra = 0
    readonly_fields = ("file", "kind", "position", "created_at")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "visibility", "moderation_status", "created_at", "deleted_at")
    list_filter = ("moderation_status", "visibility", "created_at", "deleted_at")
    search_fields = ("text", "author__phone_number", "author__email", "author__public_id")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
    inlines = (PostCommentInline, PostAttachmentInline)


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "user", "created_at")
    readonly_fields = ("post", "user", "created_at")


@admin.register(PostSave)
class PostSaveAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "user", "created_at")
    readonly_fields = ("post", "user", "created_at")


@admin.register(SocialFollow)
class SocialFollowAdmin(admin.ModelAdmin):
    list_display = ("id", "follower", "following", "status", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("follower", "following", "status", "created_at", "updated_at")


@admin.register(PostReport)
class PostReportAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "reporter", "reason", "status", "created_at", "reviewed_by")
    list_filter = ("status", "reason", "created_at")
    search_fields = ("post__text", "reporter__phone_number", "reporter__public_id", "details")
    readonly_fields = ("post", "reporter", "reason", "details", "status", "created_at", "reviewed_at", "reviewed_by")
    actions = ("mark_reviewed", "take_action")

    @admin.action(description="Mark selected reports as reviewed")
    def mark_reviewed(self, request, queryset):
        reviewed_at = timezone.now()
        for report in queryset.select_related("post"):
            report.status = PostReport.REVIEWED
            report.reviewed_by = request.user
            report.reviewed_at = reviewed_at
            report.save(update_fields=("status", "reviewed_by", "reviewed_at"))
            self.log_change(request, report, "Marked report as reviewed.")

    @admin.action(description="Hide reported posts and mark reports as actioned")
    def take_action(self, request, queryset):
        reviewed_at = timezone.now()
        for report in queryset.select_related("post"):
            post = report.post
            if post.deleted_at is None and post.moderation_status != Post.MODERATION_HIDDEN:
                post.moderation_status = Post.MODERATION_HIDDEN
                post.save(update_fields=("moderation_status", "updated_at"))
                self.log_change(request, post, f"Hidden after action on report #{report.pk}.")
            report.status = PostReport.ACTIONED
            report.reviewed_by = request.user
            report.reviewed_at = reviewed_at
            report.save(update_fields=("status", "reviewed_by", "reviewed_at"))
            self.log_change(request, report, "Took moderation action and hid the reported post.")
