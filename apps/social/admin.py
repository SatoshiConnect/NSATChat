from django.contrib import admin
from .models import Post, PostComment, PostLike


class PostCommentInline(admin.TabularInline):
    model = PostComment
    extra = 0
    readonly_fields = ("author", "text", "created_at", "deleted_at")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "visibility", "created_at", "deleted_at")
    list_filter = ("visibility", "created_at", "deleted_at")
    search_fields = ("text", "author__phone_number", "author__email", "author__public_id")
    readonly_fields = ("created_at", "updated_at")
    inlines = (PostCommentInline,)


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ("id", "post", "user", "created_at")
    readonly_fields = ("post", "user", "created_at")
