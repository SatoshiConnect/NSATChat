import mimetypes
import re
from datetime import timedelta
from uuid import uuid4

from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.chat.choices import MessageType
from apps.chat.models import ChatRoom, Message, Participant
from apps.chat.permissions import send_message_error
from apps.chat.utils import blocked_user_ids, broadcast_message, get_message_with_relations, sender_has_blocked_peer
from config.range_media import authorized_file_response
from .models import Post, PostAttachment, PostComment, PostLike, PostReport, PostSave, SocialFollow, SocialMute
from .policies import can_view_post, visible_posts_for
from .serializers import CreateCommentSerializer, CreatePostReportSerializer, PostCommentSerializer, PostSerializer


class SocialPostPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 50


class PostMediaAPIView(APIView):
    """Short-lived viewer-bound media URLs with post visibility rechecked on read."""
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def _authorized_claims(self, request, pk, attachment_id=None):
        try:
            claims = signing.loads(request.query_params.get("token", ""), salt="social.media.v1", max_age=300)
        except (BadSignature, SignatureExpired):
            raise Http404
        if claims.get("post") != pk or (attachment_id is not None and claims.get("attachment") != attachment_id):
            raise Http404
        user = User.objects.filter(pk=claims.get("viewer"), is_active=True, is_deleted=False).first()
        if not user:
            raise Http404
        post = visible_posts_for(user).filter(pk=pk).first()
        if not post:
            raise Http404
        media = post.image if attachment_id is None else PostAttachment.objects.filter(post=post, pk=attachment_id).first()
        file_field = media if attachment_id is None else getattr(media, "file", None)
        if not file_field:
            raise Http404
        return file_field

    def _response(self, request, file_field):
        return authorized_file_response(
            request,
            file_field,
            mimetypes.guess_type(file_field.name)[0] or "application/octet-stream",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Cross-Origin-Resource-Policy": "same-origin",
            },
        )

    def get(self, request, pk, attachment_id=None):
        return self._response(request, self._authorized_claims(request, pk, attachment_id))


class SocialFollowAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_follow"

    def get(self, request, user_id):
        target = get_object_or_404(User.objects.filter(is_active=True, is_deleted=False), pk=user_id)
        if target.id in blocked_user_ids(request.user.id):
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
        relation = SocialFollow.objects.filter(follower=request.user, following=target).first()
        return Response({
            "following": relation.status == SocialFollow.ACCEPTED if relation else False,
            "request_pending": relation.status == SocialFollow.PENDING if relation else False,
            "follower_count": SocialFollow.objects.filter(following=target, status=SocialFollow.ACCEPTED).count(),
            "following_count": SocialFollow.objects.filter(follower=target, status=SocialFollow.ACCEPTED).count(),
        })

    def post(self, request, user_id):
        target = get_object_or_404(User.objects.filter(is_active=True, is_deleted=False).select_related("profile"), pk=user_id)
        if target.id == request.user.id or target.id in blocked_user_ids(request.user.id):
            return Response({"detail": "You cannot follow this account."}, status=status.HTTP_404_NOT_FOUND)
        requested_status = SocialFollow.PENDING if target.profile.social_private else SocialFollow.ACCEPTED
        with transaction.atomic():
            relation, created = SocialFollow.objects.get_or_create(
                follower=request.user, following=target,
                defaults={"status": requested_status},
            )
            if not target.profile.social_private and relation.status == SocialFollow.PENDING:
                relation.status = SocialFollow.ACCEPTED
                relation.save(update_fields=("status", "updated_at"))
        return Response({"following": relation.status == SocialFollow.ACCEPTED, "request_pending": relation.status == SocialFollow.PENDING}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, user_id):
        relation = get_object_or_404(SocialFollow, follower=request.user, following_id=user_id)
        relation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SocialMuteAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_follow"

    def _target(self, request, user_id):
        target = get_object_or_404(User.objects.filter(is_active=True, is_deleted=False), pk=user_id)
        if target.id == request.user.id or target.id in blocked_user_ids(request.user.id):
            return None
        return target

    def get(self, request, user_id):
        target = self._target(request, user_id)
        if not target:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"muted": SocialMute.objects.filter(muter=request.user, muted=target).exists()})

    def post(self, request, user_id):
        target = self._target(request, user_id)
        if not target:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)
        SocialMute.objects.get_or_create(muter=request.user, muted=target)
        return Response({"muted": True}, status=status.HTTP_200_OK)

    def delete(self, request, user_id):
        SocialMute.objects.filter(muter=request.user, muted_id=user_id).delete()
        return Response({"muted": False}, status=status.HTTP_200_OK)


class SocialFollowRequestsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_follow"

    def get(self, request):
        relations = SocialFollow.objects.filter(following=request.user, status=SocialFollow.PENDING).select_related("follower", "follower__profile").order_by("created_at")[:100]
        return Response([{
            "id": relation.id,
            "created_at": relation.created_at,
            "user": UserSerializer(relation.follower, context={"request": request}).data,
        } for relation in relations])

    def post(self, request):
        try:
            relation_id = int(request.data.get("id"))
        except (TypeError, ValueError):
            return Response({"detail": "A valid follow request is required."}, status=status.HTTP_400_BAD_REQUEST)
        action = request.data.get("action")
        if action not in ("accept", "decline"):
            return Response({"detail": "Action must be accept or decline."}, status=status.HTTP_400_BAD_REQUEST)
        relation = get_object_or_404(SocialFollow, pk=relation_id, following=request.user, status=SocialFollow.PENDING)
        if relation.follower_id in blocked_user_ids(request.user.id):
            relation.delete()
            return Response({"detail": "This request is no longer available."}, status=status.HTTP_404_NOT_FOUND)
        if action == "accept":
            relation.status = SocialFollow.ACCEPTED
            relation.save(update_fields=("status", "updated_at"))
        else:
            relation.delete()
        return Response({"accepted": action == "accept"})


class SocialFollowListAPIView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer
    pagination_class = SocialPostPagination

    def get_queryset(self):
        target = get_object_or_404(User.objects.select_related("profile"), pk=self.kwargs["user_id"], is_active=True, is_deleted=False)
        if target.id != self.request.user.id and target.id in blocked_user_ids(self.request.user.id):
            return User.objects.none()
        if target.profile.social_private and target.id != self.request.user.id and not SocialFollow.objects.filter(
            follower=self.request.user, following=target, status=SocialFollow.ACCEPTED,
        ).exists():
            return User.objects.none()
        direction = self.kwargs["direction"]
        if direction not in ("followers", "following"):
            return User.objects.none()
        if direction == "followers":
            return User.objects.filter(social_following__following=target, social_following__status=SocialFollow.ACCEPTED, is_active=True, is_deleted=False).exclude(pk__in=blocked_user_ids(self.request.user.id)).order_by("id")
        return User.objects.filter(social_followers__follower=target, social_followers__status=SocialFollow.ACCEPTED, is_active=True, is_deleted=False).exclude(pk__in=blocked_user_ids(self.request.user.id)).order_by("id")


class PostFeedAPIView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    serializer_class = PostSerializer
    pagination_class = SocialPostPagination

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "social_post"
        else:
            self.throttle_scope = None
        return super().get_throttles()

    def get_queryset(self):
        liked = PostLike.objects.filter(post_id=OuterRef("pk"), user=self.request.user)
        saved = PostSave.objects.filter(post_id=OuterRef("pk"), user=self.request.user)
        following = SocialFollow.objects.filter(follower=self.request.user, following_id=OuterRef("author_id"), status=SocialFollow.ACCEPTED)
        follow_pending = SocialFollow.objects.filter(follower=self.request.user, following_id=OuterRef("author_id"), status=SocialFollow.PENDING)
        queryset = visible_posts_for(self.request.user)
        if self.request.query_params.get("scope") == "following":
            following_ids = SocialFollow.objects.filter(follower=self.request.user, status=SocialFollow.ACCEPTED).values("following_id")
            queryset = queryset.filter(Q(author=self.request.user) | Q(author_id__in=following_ids))
        elif self.request.query_params.get("scope") == "saved":
            queryset = queryset.filter(saves__user=self.request.user)
        hashtag = (self.request.query_params.get("hashtag") or "").strip().lstrip("#")
        if hashtag:
            if not re.fullmatch(r"[\w]{1,50}", hashtag, flags=re.UNICODE):
                return queryset.none()
            queryset = queryset.filter(text__icontains=f"#{hashtag}")
        return queryset.select_related("author", "author__profile").annotate(
            likes_count=Count("likes", distinct=True), comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True), distinct=True), _is_liked=Exists(liked), _is_saved=Exists(saved), _author_following=Exists(following), _author_follow_request_pending=Exists(follow_pending)
        ).order_by("-created_at", "-id")

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class PostDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_throttles(self):
        self.throttle_scope = "social_interaction" if self.request.method in ("POST", "PATCH", "DELETE") else None
        return super().get_throttles()

    def post_obj(self, request, pk):
        return get_object_or_404(visible_posts_for(request.user), pk=pk)

    def get(self, request, pk):
        post = self.post_obj(request, pk)
        liked = PostLike.objects.filter(post_id=OuterRef("pk"), user=request.user)
        saved = PostSave.objects.filter(post_id=OuterRef("pk"), user=request.user)
        post = Post.objects.filter(pk=post.pk).select_related("author", "author__profile").annotate(
            likes_count=Count("likes", distinct=True),
            comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True), distinct=True),
            _is_liked=Exists(liked),
            _is_saved=Exists(saved),
        ).get()
        return Response(PostSerializer(post, context={"request": request}).data)

    def post(self, request, pk):
        post = self.post_obj(request, pk)
        reaction = request.data.get("reaction", "LIKE")
        if reaction not in dict(PostLike.REACTION_CHOICES):
            return Response({"detail": "Choose a supported reaction."}, status=status.HTTP_400_BAD_REQUEST)
        like = PostLike.objects.filter(post=post, user=request.user).first()
        if like and like.reaction == reaction:
            like.delete()
            selected = None
        elif like:
            like.reaction = reaction
            like.save(update_fields=("reaction",))
            selected = reaction
        else:
            PostLike.objects.create(post=post, user=request.user, reaction=reaction)
            selected = reaction
        return Response({"liked": bool(selected), "reaction": selected, "likes_count": post.likes.count()})

    def delete(self, request, pk):
        post = get_object_or_404(Post, pk=pk, author=request.user, deleted_at__isnull=True)
        post.deleted_at = timezone.now()
        post.save(update_fields=("deleted_at", "updated_at"))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, pk):
        post = get_object_or_404(Post, pk=pk, author=request.user, deleted_at__isnull=True)
        serializer = PostSerializer(post, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        liked = PostLike.objects.filter(post_id=OuterRef("pk"), user=request.user)
        saved = PostSave.objects.filter(post_id=OuterRef("pk"), user=request.user)
        updated = visible_posts_for(request.user).filter(pk=post.pk).select_related("author", "author__profile").annotate(
            likes_count=Count("likes", distinct=True),
            comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True), distinct=True),
            _is_liked=Exists(liked),
            _is_saved=Exists(saved),
        ).get()
        return Response(PostSerializer(updated, context={"request": request}).data)


class PostSaveAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        _, created = PostSave.objects.get_or_create(post=post, user=request.user)
        return Response({"saved": True}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        PostSave.objects.filter(post=post, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SharePostToChatAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_interaction"

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        try:
            room_id = int(request.data.get("room_id"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a chat first."}, status=status.HTTP_400_BAD_REQUEST)
        room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
        denied = send_message_error(request.user, room)
        if denied:
            return Response({"detail": denied}, status=status.HTTP_403_FORBIDDEN)
        if sender_has_blocked_peer(room, request.user):
            return Response({"detail": "Unblock this contact to send a message."}, status=status.HTTP_403_FORBIDDEN)
        recipient_ids = Participant.objects.filter(room=room, joined_at__lte=timezone.now()).exclude(user=request.user).values_list("user_id", flat=True)
        recipients = User.objects.filter(pk__in=recipient_ids, is_active=True, is_deleted=False)
        if not recipients.exists() or any(not can_view_post(post, recipient) for recipient in recipients):
            return Response({"detail": "Everyone in this chat must have permission to view this post."}, status=status.HTTP_403_FORBIDDEN)
        expires_at = timezone.now() + timedelta(seconds=room.disappearing_seconds) if room.disappearing_seconds else None
        message = Message.objects.create(
            room=room,
            sender=request.user,
            message_type=MessageType.TEXT,
            content="Shared a post",
            client_message_id=f"social-share-{post.pk}-{request.user.pk}-{uuid4().hex[:12]}",
            status_ref={"kind": "social_post", "post_id": post.pk},
            expires_at=expires_at,
        )
        message = get_message_with_relations(message.pk)
        broadcast_message(message, request)
        from apps.chat.serializers import MessageSerializer
        return Response({"message": "Post shared to chat.", "data": MessageSerializer(message, context={"request": request}).data}, status=status.HTTP_201_CREATED)


class PostCommentsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_throttles(self):
        self.throttle_scope = "social_comment" if self.request.method == "POST" else None
        return super().get_throttles()

    def get(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        comments = post.comments.filter(deleted_at__isnull=True, parent__isnull=True).select_related(
            "author", "author__profile", "sticker_asset", "sticker_asset__item"
        )
        return Response(PostCommentSerializer(comments, many=True, context={"request": request}).data)

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        serializer = CreateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attrs = dict(serializer.validated_data)
        parent_id = attrs.pop("parent_id", None)
        sticker_asset_id = attrs.pop("sticker_asset_id", None)
        is_reward = attrs.pop("is_reward", False)
        parent = None
        if parent_id:
            parent = get_object_or_404(PostComment, pk=parent_id, post=post, deleted_at__isnull=True, parent__isnull=True)
        sticker_asset = None
        if sticker_asset_id:
            from apps.marketplace.models import DigitalItemAsset, DigitalItem

            sticker_asset = DigitalItemAsset.objects.filter(
                pk=sticker_asset_id,
                item__kind=DigitalItem.Kind.STICKER_PACK,
            ).filter(
                Q(item__entitlements__owner=request.user, item__entitlements__revoked_at__isnull=True)
                | Q(item__inventory_entries__owner=request.user, item__state=DigitalItem.State.APPROVED)
            ).select_related("item").first()
            if not sticker_asset:
                return Response({"detail": "That sticker is not in your library."}, status=status.HTTP_403_FORBIDDEN)
        comment = PostComment.objects.create(
            post=post, author=request.user, parent=parent, sticker_asset=sticker_asset, is_reward=is_reward, **attrs
        )
        comment = PostComment.objects.select_related("author", "author__profile", "sticker_asset", "sticker_asset__item").get(pk=comment.pk)
        return Response(PostCommentSerializer(comment, context={"request": request}).data, status=status.HTTP_201_CREATED)


class PostCommentDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_throttles(self):
        self.throttle_scope = "social_comment" if self.request.method in ("PATCH", "DELETE") else None
        return super().get_throttles()

    def owned_comment(self, request, post_pk, comment_pk):
        get_object_or_404(visible_posts_for(request.user), pk=post_pk)
        return get_object_or_404(
            PostComment.objects.select_related("author", "author__profile"),
            pk=comment_pk,
            post_id=post_pk,
            author=request.user,
            deleted_at__isnull=True,
        )

    def patch(self, request, post_pk, comment_pk):
        comment = self.owned_comment(request, post_pk, comment_pk)
        serializer = CreateCommentSerializer(data=request.data, context={"allow_existing_sticker": bool(comment.sticker_asset_id)})
        serializer.is_valid(raise_exception=True)
        comment.text = serializer.validated_data["text"]
        comment.save(update_fields=("text",))
        return Response(PostCommentSerializer(comment, context={"request": request}).data)

    def delete(self, request, post_pk, comment_pk):
        comment = self.owned_comment(request, post_pk, comment_pk)
        comment.deleted_at = timezone.now()
        comment.save(update_fields=("deleted_at",))
        return Response(status=status.HTTP_204_NO_CONTENT)


class PostReportAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_report"

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        if post.author_id == request.user.id:
            return Response({"detail": "You cannot report your own post."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = CreatePostReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report, created = PostReport.objects.get_or_create(
            post=post,
            reporter=request.user,
            defaults=serializer.validated_data,
        )
        if created and post.moderation_status == Post.MODERATION_ACTIVE:
            Post.objects.filter(pk=post.pk, moderation_status=Post.MODERATION_ACTIVE).update(
                moderation_status=Post.MODERATION_REVIEW
            )
        return Response(
            {"reported": True, "already_reported": not created, "detail": "Thanks. Your report was sent for review."},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
