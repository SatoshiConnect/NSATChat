import os
import re

from django.core import signing
from django.db.models import Count
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers
from apps.accounts.serializers import UserSerializer
from .models import Post, PostAttachment, PostComment, PostReport


IMAGE_LIMIT = 8 * 1024 * 1024
VIDEO_LIMIT = 50 * 1024 * 1024
ALLOWED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_SIGNATURES = (b"\x1aE\xdf\xa3",)


def _sniff_upload(upload):
    upload.seek(0)
    header = upload.read(32)
    upload.seek(0)
    return header


def _valid_video(upload):
    header = _sniff_upload(upload)
    extension = os.path.splitext(upload.name)[1].lower()
    if extension == ".mp4" or extension == ".m4v" or extension == ".mov":
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if extension == ".webm":
        return header.startswith(VIDEO_SIGNATURES)
    return False


def _validate_image(upload, field):
    extension = os.path.splitext(upload.name)[1].lower()
    if extension not in ALLOWED_IMAGES or upload.size > IMAGE_LIMIT:
        raise serializers.ValidationError({field: "Each image must be JPEG, PNG, WebP, or GIF and 8 MB or smaller."})
    try:
        upload.seek(0)
        with Image.open(upload) as image:
            if image.width > 12000 or image.height > 12000 or image.width * image.height > 50_000_000:
                raise serializers.ValidationError({field: "Image dimensions are too large."})
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise serializers.ValidationError({field: "The uploaded image is invalid."})
    finally:
        upload.seek(0)


class PostCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    parent_id = serializers.IntegerField(read_only=True)
    replies = serializers.SerializerMethodField()

    class Meta:
        model = PostComment
        fields = ("id", "author", "parent_id", "text", "created_at", "replies")
        read_only_fields = fields

    def get_replies(self, obj):
        replies = list(obj.replies.filter(deleted_at__isnull=True).select_related("author", "author__profile").order_by("created_at", "id"))
        return [{
            "id": reply.id,
            "parent_id": reply.parent_id,
            "author": UserSerializer(reply.author, context=self.context).data,
            "text": reply.text,
            "created_at": reply.created_at,
            "replies": [],
        } for reply in replies]


class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    comments = serializers.SerializerMethodField()
    likes_count = serializers.IntegerField(read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    my_reaction = serializers.SerializerMethodField()
    reactions = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    hashtags = serializers.SerializerMethodField()
    uploads = serializers.ListField(child=serializers.FileField(), write_only=True, required=False, max_length=9)

    class Meta:
        model = Post
        fields = ("id", "author", "text", "image", "attachments", "hashtags", "uploads", "visibility", "created_at", "updated_at", "likes_count", "comments_count", "is_liked", "is_saved", "my_reaction", "reactions", "comments")
        read_only_fields = ("id", "author", "created_at", "updated_at", "likes_count", "comments_count", "is_liked", "is_saved", "comments")

    def get_is_liked(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(obj, "_is_liked"):
            return obj._is_liked
        return obj.likes.filter(user=request.user).exists()

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(obj, "_is_saved"):
            return obj._is_saved
        return obj.saves.filter(user=request.user).exists()

    def get_my_reaction(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        return obj.likes.filter(user=request.user).values_list("reaction", flat=True).first()

    def get_reactions(self, obj):
        counts = obj.likes.values("reaction").annotate(count=Count("id"))
        return {row["reaction"]: row["count"] for row in counts}

    def _media_url(self, obj, attachment=None):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None
        claims = {"post": obj.pk, "viewer": request.user.pk}
        if attachment is not None:
            claims["attachment"] = attachment.pk
        token = signing.dumps(claims, salt="social.media.v1", compress=True)
        suffix = f"attachments/{attachment.pk}/" if attachment is not None else "image/"
        return request.build_absolute_uri(f"/api/social/posts/{obj.pk}/media/{suffix}?token={token}")

    def get_image(self, obj):
        if not obj.image:
            return None
        return self._media_url(obj)

    def get_attachments(self, obj):
        return [{"id": item.pk, "kind": item.kind, "url": self._media_url(obj, item)} for item in obj.attachments.all()]

    def get_hashtags(self, obj):
        return list(dict.fromkeys(match.casefold() for match in re.findall(r"(?<!\w)#([\w]{1,50})", obj.text or "")))

    def get_comments(self, obj):
        # Keep feed response size bounded even for posts with long comment histories.
        recent = list(obj.comments.filter(deleted_at__isnull=True, parent__isnull=True).select_related("author", "author__profile").order_by("-created_at", "-id")[:3])
        recent.reverse()
        return PostCommentSerializer(recent, many=True, context=self.context).data

    def validate(self, attrs):
        text = str(attrs.get("text") or "").strip()
        image = attrs.get("image")
        uploads = attrs.get("uploads", [])
        attachments = getattr(self.instance, "attachments", None)
        has_existing_media = bool(getattr(self.instance, "image", None)) or bool(attachments and attachments.exists())
        if not text and not image and not uploads and not has_existing_media:
            raise serializers.ValidationError("A post needs text or an image.")
        if image:
            _validate_image(image, "image")
        images, videos = [], []
        for upload in uploads:
            extension = os.path.splitext(upload.name)[1].lower()
            if extension in ALLOWED_IMAGES:
                _validate_image(upload, "uploads")
                images.append(upload)
            elif extension in {".mp4", ".m4v", ".mov", ".webm"} and upload.size <= VIDEO_LIMIT and _valid_video(upload):
                videos.append(upload)
            else:
                raise serializers.ValidationError({"uploads": "Upload valid JPEG, PNG, WebP, GIF, MP4, MOV, M4V, or WebM files within the size limits."})
        image_count = len(images) + (1 if image else 0)
        if image_count > 8 or len(videos) > 1 or (videos and image_count):
            raise serializers.ValidationError({"uploads": "A post can contain up to 8 images or one video."})
        if sum(item.size for item in images) + (image.size if image else 0) > 32 * 1024 * 1024:
            raise serializers.ValidationError({"uploads": "Combined images must be 32 MB or smaller."})
        attrs["text"] = text
        return attrs

    def create(self, validated_data):
        uploads = validated_data.pop("uploads", [])
        post = super().create(validated_data)
        for position, upload in enumerate(uploads):
            extension = os.path.splitext(upload.name)[1].lower()
            kind = PostAttachment.VIDEO if extension in {".mp4", ".m4v", ".mov", ".webm"} else PostAttachment.IMAGE
            PostAttachment.objects.create(post=post, file=upload, kind=kind, position=position)
        return post


class CreateCommentSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=1000, trim_whitespace=True)
    parent_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate_text(self, value):
        if not value.strip():
            raise serializers.ValidationError("Comment cannot be empty.")
        return value.strip()


class CreatePostReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostReport
        fields = ("reason", "details")

    def validate_details(self, value):
        return (value or "").strip()
