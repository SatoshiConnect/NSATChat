from rest_framework import serializers
from apps.accounts.serializers import UserSerializer
from .models import Post, PostComment


class PostCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = PostComment
        fields = ("id", "author", "text", "created_at")
        read_only_fields = fields


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = ("id", "author", "text", "image", "visibility", "created_at", "updated_at", "likes_count", "comments_count", "is_liked", "comments")
        read_only_fields = ("id", "author", "created_at", "updated_at", "likes_count", "comments_count", "is_liked", "comments")

    def get_is_liked(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(obj, "_is_liked"):
            return obj._is_liked
        return obj.likes.filter(user=request.user).exists()

    def get_comments(self, obj):
        # Keep feed response size bounded even for posts with long comment histories.
        recent = list(obj.comments.filter(deleted_at__isnull=True).select_related("author", "author__profile").order_by("-created_at", "-id")[:3])
        recent.reverse()
        return PostCommentSerializer(recent, many=True, context=self.context).data

    def validate(self, attrs):
        text = str(attrs.get("text") or "").strip()
        image = attrs.get("image")
        if not text and not image:
            raise serializers.ValidationError("A post needs text or an image.")
        if image:
            if image.size > 8 * 1024 * 1024:
                raise serializers.ValidationError({"image": "Image must be 8 MB or smaller."})
            content_type = str(getattr(image, "content_type", "") or "").lower()
            if content_type and content_type not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                raise serializers.ValidationError({"image": "Upload a JPEG, PNG, WebP, or GIF image."})
            if not image.name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                raise serializers.ValidationError({"image": "Upload a JPEG, PNG, WebP, or GIF image."})
        attrs["text"] = text
        return attrs


class CreateCommentSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Comment cannot be empty.")
        return value.strip()
