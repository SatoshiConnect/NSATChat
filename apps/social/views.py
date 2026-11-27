import mimetypes
import hashlib
import hmac
import re
from datetime import timedelta
from uuid import uuid4

from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.conf import settings
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
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.chat.choices import MessageType
from apps.chat.models import ChatRoom, Message, Participant
from apps.chat.permissions import send_message_error
from apps.chat.utils import blocked_user_ids, broadcast_message, get_message_with_relations, sender_has_blocked_peer
from config.range_media import authorized_file_response
from .models import LiveStream, LiveStreamEvent, LiveStreamViewer, Post, PostAttachment, PostComment, PostLike, PostReport, PostSave, SocialFollow, SocialMute
from .policies import can_view_post, visible_posts_for
from .serializers import CreateCommentSerializer, CreatePostReportSerializer, PostCommentSerializer, PostSerializer


class SocialPostPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 50


LIVE_STICKERS = {"sparkles", "heart", "laugh", "clap", "fire", "thumbs-up", "hug", "party"}
LIVE_REACTIONS = {"❤️", "👍", "😂", "😮", "🔥", "👏"}


def _live_user(user, request):
    profile = getattr(user, "profile", None)
    picture = getattr(profile, "profile_picture", None)
    try:
        picture_url = request.build_absolute_uri(picture.url) if picture else ""
    except (ValueError, AttributeError):
        picture_url = ""
    return {
        "id": user.pk,
        "public_id": user.public_id,
        "display_name": getattr(profile, "display_name", "") or user.public_id,
        "profile_picture": picture_url,
    }


def _live_event_data(event, request):
    sticker = None
    if event.sticker_asset_id and event.sticker_asset:
        try:
            sticker = {
                "id": event.sticker_asset_id,
                "file": request.build_absolute_uri(event.sticker_asset.image.url),
                "pack_title": event.sticker_asset.item.title,
            }
        except (ValueError, AttributeError):
            sticker = None
    return {
        "id": event.pk,
        "kind": event.kind,
        "text": event.text,
        "sticker_code": event.sticker_code,
        "sticker": sticker,
        "actor": _live_user(event.actor, request),
        "created_at": event.created_at,
    }


def _live_stream_data(stream, request):
    viewer_count = getattr(stream, "active_viewer_count", None)
    if viewer_count is None:
        viewer_count = stream.viewers.filter(last_seen__gte=timezone.now() - timedelta(minutes=2)).count()
    return {
        "id": stream.pk,
        "title": stream.title,
        "host": _live_user(stream.host, request),
        "started_at": stream.started_at,
        "viewer_count": viewer_count,
        "viewer_limit": stream.viewer_limit,
        "is_live": stream.status == LiveStream.LIVE,
    }


def _can_join_live(user, stream):
    if user.id == stream.host_id:
        return True
    if stream.host_id in blocked_user_ids(user.id) or user.id in blocked_user_ids(stream.host_id):
        return False
    if SocialMute.objects.filter(muter=user, muted=stream.host).exists():
        return False
    profile = getattr(stream.host, "profile", None)
    if profile and profile.social_private:
        return SocialFollow.objects.filter(follower=user, following=stream.host, status=SocialFollow.ACCEPTED).exists()
    return True


def _broadcast_live(stream_id, event, payload):
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(f"social_live_{stream_id}", {"type": "live.event", "event": event, "payload": payload})


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


class LiveStreamListCreateAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_live"

    def get(self, request):
        cutoff = timezone.now() - timedelta(minutes=2)
        streams = LiveStream.objects.filter(status=LiveStream.LIVE, last_heartbeat__gte=cutoff).select_related(
            "host", "host__profile"
        ).annotate(
            active_viewer_count=Count("viewers", filter=Q(viewers__last_seen__gte=cutoff))
        )[:30]
        return Response([_live_stream_data(stream, request) for stream in streams if _can_join_live(request.user, stream)])

    def post(self, request):
        title = str(request.data.get("title") or "").strip()[:100]
        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            now = timezone.now()
            stale_streams = LiveStream.objects.filter(host=request.user, status=LiveStream.LIVE, last_heartbeat__lt=now - timedelta(minutes=2))
            stale_ids = list(stale_streams.values_list("id", flat=True))
            stale_streams.update(status=LiveStream.ENDED, ended_at=now)
            LiveStreamViewer.objects.filter(stream_id__in=stale_ids).delete()
            if LiveStream.objects.select_for_update().filter(host=request.user, status=LiveStream.LIVE).exists():
                return Response({"code": "live_already_active", "detail": "You already have an active live stream."}, status=status.HTTP_409_CONFLICT)
            stream = LiveStream.objects.create(
                host=request.user,
                title=title,
                viewer_limit=settings.SOCIAL_LIVE_MAX_VIEWERS,
            )
        return Response(_live_stream_data(stream, request), status=status.HTTP_201_CREATED)


class LiveStreamTokenAPIView(APIView):
    """Issue short-lived, role-limited credentials for the configured LiveKit SFU."""

    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_live"

    def post(self, request, pk):
        if not (settings.LIVEKIT_PUBLIC_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
            return Response(
                {"code": "live_media_unconfigured", "detail": "Live streaming is not enabled on this server yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        stream = get_object_or_404(
            LiveStream.objects.select_related("host", "host__profile"),
            pk=pk,
            status=LiveStream.LIVE,
        )
        if stream.last_heartbeat < timezone.now() - timedelta(minutes=2) or not _can_join_live(request.user, stream):
            raise Http404
        is_host = request.user.pk == stream.host_id
        if not is_host and not LiveStreamViewer.objects.filter(
            stream=stream,
            user=request.user,
            last_seen__gte=timezone.now() - timedelta(minutes=2),
        ).exists():
            return Response({"detail": "Join this live before requesting media access."}, status=status.HTTP_403_FORBIDDEN)

        from livekit import api

        token = (
            api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
            .with_identity(
                "u" + hmac.new(
                    settings.SECRET_KEY.encode(),
                    f"live:{stream.pk}:{request.user.pk}".encode(),
                    hashlib.sha256,
                ).hexdigest()[:32]
            )
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=f"nsat-live-{stream.pk}",
                    can_publish=is_host,
                    can_subscribe=True,
                    can_publish_data=False,
                )
            )
            .with_ttl(timedelta(minutes=10))
            .to_jwt()
        )
        return Response({"url": settings.LIVEKIT_PUBLIC_URL, "token": token})


class LiveStreamDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_live"

    def get_stream(self, request, pk):
        stream = get_object_or_404(LiveStream.objects.select_related("host", "host__profile"), pk=pk, status=LiveStream.LIVE)
        if stream.last_heartbeat < timezone.now() - timedelta(minutes=2) or not _can_join_live(request.user, stream):
            raise Http404
        return stream

    def get(self, request, pk):
        stream = self.get_stream(request, pk)
        events = list(stream.events.select_related("actor", "actor__profile", "sticker_asset", "sticker_asset__item").order_by("-id")[:50])
        events.reverse()
        return Response({**_live_stream_data(stream, request), "events": [_live_event_data(event, request) for event in events]})

    def post(self, request, pk):
        stream = self.get_stream(request, pk)
        if request.user.id != stream.host_id and not LiveStreamViewer.objects.filter(
            stream=stream,
            user=request.user,
            last_seen__gte=timezone.now() - timedelta(minutes=2),
        ).exists():
            return Response({"detail": "Join this live before sending an interaction."}, status=status.HTTP_403_FORBIDDEN)
        kind = str(request.data.get("kind") or "").upper()
        text = str(request.data.get("text") or "").strip()
        sticker_code = str(request.data.get("sticker_code") or "").strip().lower()
        raw_sticker_asset_id = request.data.get("sticker_asset_id")
        try:
            sticker_asset_id = int(raw_sticker_asset_id) if raw_sticker_asset_id not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "Choose a valid sticker from your library."}, status=status.HTTP_400_BAD_REQUEST)
        if kind not in (LiveStreamEvent.COMMENT, LiveStreamEvent.REACTION, LiveStreamEvent.STICKER):
            return Response({"detail": "Choose a comment, reaction, or free sticker."}, status=status.HTTP_400_BAD_REQUEST)
        if kind == LiveStreamEvent.COMMENT and not text:
            return Response({"detail": "Write a comment first."}, status=status.HTTP_400_BAD_REQUEST)
        if kind == LiveStreamEvent.REACTION and text not in LIVE_REACTIONS:
            return Response({"detail": "This reaction is not available."}, status=status.HTTP_400_BAD_REQUEST)
        sticker_asset = None
        if kind == LiveStreamEvent.STICKER and sticker_asset_id:
            if sticker_code:
                return Response({"detail": "Choose one sticker."}, status=status.HTTP_400_BAD_REQUEST)
            from apps.marketplace.models import DigitalItem, DigitalItemAsset

            sticker_asset = DigitalItemAsset.objects.filter(
                pk=sticker_asset_id,
                item__kind=DigitalItem.Kind.STICKER_PACK,
                item__state=DigitalItem.State.APPROVED,
            ).filter(
                Q(item__entitlements__owner=request.user, item__entitlements__revoked_at__isnull=True)
                | Q(item__inventory_entries__owner=request.user)
            ).select_related("item").first()
            if not sticker_asset:
                return Response({"detail": "That sticker is not in your library."}, status=status.HTTP_403_FORBIDDEN)
        elif kind == LiveStreamEvent.STICKER and sticker_code not in LIVE_STICKERS:
            return Response({"detail": "This free sticker is not available."}, status=status.HTTP_400_BAD_REQUEST)
        elif kind != LiveStreamEvent.STICKER and sticker_asset_id:
            return Response({"detail": "Only sticker events can include a sticker."}, status=status.HTTP_400_BAD_REQUEST)
        event = LiveStreamEvent.objects.create(
            stream=stream,
            actor=request.user,
            kind=kind,
            text=text[:240] if kind in (LiveStreamEvent.COMMENT, LiveStreamEvent.REACTION) else "",
            sticker_code=sticker_code if kind == LiveStreamEvent.STICKER else "",
            sticker_asset=sticker_asset,
        )
        if event.pk % 100 == 0:
            newest_event_ids = stream.events.order_by("-id").values("pk")[:1000]
            LiveStreamEvent.objects.filter(stream=stream).exclude(pk__in=newest_event_ids).delete()
        payload = _live_event_data(event, request)
        _broadcast_live(stream.pk, "live_event", payload)
        return Response(payload, status=status.HTTP_201_CREATED)


class LiveStreamHeartbeatAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_live"

    def post(self, request, pk):
        stream = get_object_or_404(LiveStream, pk=pk, host=request.user, status=LiveStream.LIVE)
        stream.last_heartbeat = timezone.now()
        stream.save(update_fields=("last_heartbeat",))
        return Response({"ok": True})


class LiveStreamEndAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "social_live"

    def post(self, request, pk):
        stream = get_object_or_404(LiveStream, pk=pk, host=request.user, status=LiveStream.LIVE)
        stream.status = LiveStream.ENDED
        stream.ended_at = timezone.now()
        stream.save(update_fields=("status", "ended_at"))
        LiveStreamViewer.objects.filter(stream=stream).delete()
        _broadcast_live(stream.pk, "stream_ended", {"stream_id": stream.pk})
        return Response({"ok": True, "stream_id": stream.pk})


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
        sticker_code = attrs.pop("sticker_code", "")
        is_reward = attrs.pop("is_reward", False)
        if is_reward and post.author_id == request.user.id:
            return Response({"detail": "You cannot reward your own post."}, status=status.HTTP_400_BAD_REQUEST)
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
        with transaction.atomic():
            comment = PostComment.objects.create(
                post=post, author=request.user, parent=parent, sticker_asset=sticker_asset,
                sticker_code=sticker_code, is_reward=is_reward, **attrs
            )
            if is_reward:
                from apps.marketplace.models import CreatorNotification

                CreatorNotification.objects.create(
                    recipient=post.author,
                    actor=request.user,
                    item=sticker_asset.item if sticker_asset else None,
                    event_type="social_sticker_reward",
                    message=(f"You received a {sticker_asset.item.title[:70]} sticker reward on your post."
                             if sticker_asset else "You received a free starter sticker reward on your post."),
                )
            comment = PostComment.objects.select_related(
                "author", "author__profile", "sticker_asset", "sticker_asset__item"
            ).get(pk=comment.pk)
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
