import json
import uuid
import mimetypes
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Prefetch
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.http import FileResponse, Http404

from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.chat.models import ChatRoom, Message, Participant
from apps.chat.choices import MessageType, RoomType
from apps.chat.serializers import MessageSerializer
from apps.accounts.models import Contact, User
from apps.accounts.serializers import UserSerializer
from apps.social.models import SocialMute

from apps.status.policies import can_view_status
from drf_spectacular.utils import (
    extend_schema,
    OpenApiRequest,
    OpenApiResponse,
)


from .models import (
    Status,
    StatusView,
    StatusReaction,
    StatusHighlight,
    StatusHighlightItem,
    StatusReport,
)

from .utils import status_contact_ids, notify_status_feed_changed, notify_status_viewed, notify_status_mentioned
from .serializers import (
    StatusSerializer,
    UploadStatusSerializer,
    StatusViewSerializer,
    ContactStatusSerializer,
    StatusPrivacySerializer,
    ReactToStatusSerializer,
    StatusHighlightSerializer,
    CreateStatusHighlightSerializer,
    CreateStatusReportSerializer,
    UpdateStatusContentSerializer,
)


def _highlight_viewer_context(request):
    contact_ids = set(Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True))
    contact_ids |= set(Participant.objects.filter(
        room__room_type=RoomType.PRIVATE, room__is_active=True,
        room__participants__user=request.user,
    ).exclude(user=request.user).values_list("user_id", flat=True))
    saved_me_ids = set(Contact.objects.filter(contact_user=request.user).values_list("owner_id", flat=True))
    from apps.chat.utils import blocked_user_ids
    muted_ids = set(SocialMute.objects.filter(muter=request.user).values_list("muted_id", flat=True))
    return contact_ids, saved_me_ids, blocked_user_ids(request.user.id) | muted_ids


def _highlight_visible_items(request, highlight, viewer_context=None):
    """Return live source stories that this viewer is still allowed to see."""
    if hasattr(highlight, "_prefetched_objects_cache") and "items" in highlight._prefetched_objects_cache:
        items = list(highlight.items.all())
    else:
        items = list(highlight.items.select_related("status", "status__user", "status__user__profile").prefetch_related("status__privacy_rules", "status__views", "status__mentions").all())
    if highlight.owner_id == request.user.id:
        return [item.status for item in items if not item.status.is_deleted]
    contact_ids, saved_me_ids, blocked = viewer_context or _highlight_viewer_context(request)
    if highlight.owner_id in blocked:
        return []
    return [item.status for item in items if can_view_status(
        item.status, request.user, contact_ids, saved_me_ids, allow_expired=True
    )]


class StatusHighlightsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        owner_id = request.query_params.get("owner_id")
        if owner_id is not None and (not owner_id.isdigit() or int(owner_id) <= 0):
            return Response({"detail": "Invalid owner_id."}, status=status.HTTP_400_BAD_REQUEST)
        owner_id = int(owner_id) if owner_id else request.user.id
        item_queryset = StatusHighlightItem.objects.select_related("status", "status__user", "status__user__profile").prefetch_related("status__privacy_rules", "status__views", "status__mentions")
        highlights = StatusHighlight.objects.filter(
            owner_id=owner_id, owner__is_active=True, owner__is_deleted=False,
        ).prefetch_related(Prefetch("items", queryset=item_queryset)).order_by("position", "id")
        viewer_context = None if owner_id == request.user.id else _highlight_viewer_context(request)
        visible = {}
        result = []
        for highlight in highlights:
            statuses = _highlight_visible_items(request, highlight, viewer_context)
            if statuses:
                visible[highlight.id] = statuses
                result.append(highlight)
        return Response(StatusHighlightSerializer(result, many=True, context={"request": request, "visible_statuses": visible}).data)

    def post(self, request):
        serializer = CreateStatusHighlightSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if StatusHighlight.objects.filter(owner=request.user).count() >= 20:
            return Response({"detail": "You can have up to 20 highlights."}, status=status.HTTP_400_BAD_REQUEST)
        highlight = serializer.save(owner=request.user, position=StatusHighlight.objects.filter(owner=request.user).count())
        return Response(StatusHighlightSerializer(highlight, context={"request": request, "visible_statuses": {highlight.id: []}}).data, status=status.HTTP_201_CREATED)


class StatusHighlightDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def _owned(self, request, pk):
        return get_object_or_404(StatusHighlight, pk=pk, owner=request.user)

    def patch(self, request, pk):
        highlight = self._owned(request, pk)
        if "title" in request.data:
            serializer = CreateStatusHighlightSerializer(highlight, data={"title": request.data["title"]}, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
        if "cover_status_id" in request.data:
            value = request.data.get("cover_status_id")
            if value in (None, ""):
                highlight.cover_status = None
            else:
                cover = get_object_or_404(StatusHighlightItem, highlight=highlight, status_id=value)
                highlight.cover_status = cover.status
            highlight.save(update_fields=("cover_status", "updated_at"))
        visible = {highlight.id: _highlight_visible_items(request, highlight)}
        return Response(StatusHighlightSerializer(highlight, context={"request": request, "visible_statuses": visible}).data)

    def delete(self, request, pk):
        self._owned(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatusHighlightItemsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, pk):
        highlight = get_object_or_404(StatusHighlight, pk=pk, owner=request.user)
        status_id = request.data.get("status_id")
        story = get_object_or_404(Status, pk=status_id, user=request.user, is_deleted=False, expires_at__gt=timezone.now())
        if highlight.items.count() >= 100:
            return Response({"detail": "A highlight can contain up to 100 stories."}, status=status.HTTP_400_BAD_REQUEST)
        item, created = StatusHighlightItem.objects.get_or_create(
            highlight=highlight, status=story,
            defaults={"position": highlight.items.count()},
        )
        if created and not highlight.cover_status_id:
            highlight.cover_status = story
            highlight.save(update_fields=("cover_status", "updated_at"))
        visible = {highlight.id: _highlight_visible_items(request, highlight)}
        return Response(StatusHighlightSerializer(highlight, context={"request": request, "visible_statuses": visible}).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk, status_id):
        highlight = get_object_or_404(StatusHighlight, pk=pk, owner=request.user)
        item = get_object_or_404(StatusHighlightItem, highlight=highlight, status_id=status_id)
        was_cover = highlight.cover_status_id == item.status_id
        item.delete()
        if was_cover:
            highlight.cover_status = highlight.items.order_by("position", "id").values_list("status", flat=True).first()
            highlight.save(update_fields=("cover_status", "updated_at"))
        return Response(status=status.HTTP_204_NO_CONTENT)


class StatusMediaAPIView(APIView):
    """Serve status media only through a short-lived viewer-bound capability URL."""
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def get(self, request, pk):
        token = request.query_params.get("token", "")
        try:
            claims = signing.loads(token, salt="status.media.v1", max_age=300)
        except (BadSignature, SignatureExpired):
            raise Http404
        if claims.get("status") != pk:
            raise Http404
        viewer = User.objects.filter(pk=claims.get("viewer"), is_active=True, is_deleted=False).first()
        story = Status.objects.filter(pk=pk, is_deleted=False).select_related("user", "user__profile").first()
        if not viewer or not story or not story.media:
            raise Http404
        highlighted = story.highlight_items.filter(highlight__owner=story.user).exists()
        active = story.expires_at > timezone.now()
        if viewer.id == story.user_id:
            allowed = active or highlighted
        else:
            contact_ids = set(Contact.objects.filter(owner=viewer).values_list("contact_user_id", flat=True))
            contact_ids |= set(Participant.objects.filter(
                room__room_type=RoomType.PRIVATE, room__is_active=True,
                room__participants__user=viewer,
            ).exclude(user=viewer).values_list("user_id", flat=True))
            from apps.chat.utils import blocked_user_ids
            blocked = blocked_user_ids(viewer.id) | set(SocialMute.objects.filter(muter=viewer).values_list("muted_id", flat=True))
            allowed = story.user_id not in blocked and (active or highlighted) and can_view_status(
                story, viewer, contact_ids, allow_expired=highlighted,
            )
        if not allowed:
            raise Http404
        try:
            file_handle = story.media.open("rb")
        except (OSError, ValueError, FileNotFoundError):
            raise Http404
        response = FileResponse(file_handle, content_type=mimetypes.guess_type(story.media.name)[0] or "application/octet-stream")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


class ReorderStatusHighlightsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        ids = request.data.get("ids")
        if not isinstance(ids, list) or any(not isinstance(value, int) for value in ids):
            return Response({"detail": "ids must be a list of highlight IDs."}, status=status.HTTP_400_BAD_REQUEST)
        owned = list(StatusHighlight.objects.filter(owner=request.user).order_by("position", "id").values_list("id", flat=True))
        if len(ids) != len(set(ids)) or set(ids) != set(owned):
            return Response({"detail": "Include each of your highlights exactly once."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for position, highlight_id in enumerate(ids):
                StatusHighlight.objects.filter(pk=highlight_id, owner=request.user).update(position=position)
        return Response({"detail": "Highlights reordered."})


class StatusContactsAPIView(APIView):
    """List saved contacts and existing private-chat contacts for status privacy controls."""
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Contacts for status privacy", tags=["Status"])
    def get(self, request):
        # The current SatoshiCore Contacts UI is populated from existing private
        # conversations as well as saved Contact records. Include both sources
        # so the privacy picker does not omit a contact visible in the app.
        saved_ids = set(Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True))
        private_chat_ids = Participant.objects.filter(
            room__room_type=RoomType.PRIVATE,
            room__is_active=True,
            room__participants__user=request.user,
        ).exclude(user=request.user).values_list("user_id", flat=True)
        contact_ids = saved_ids | set(private_chat_ids)
        users = User.objects.filter(
            id__in=contact_ids, is_active=True, is_deleted=False
        ).exclude(pk=request.user.pk).select_related("profile").order_by("profile__display_name", "phone_number")
        data = []
        for user in users:
            data.append({"user": UserSerializer(user, context={"request": request}).data})
        return Response(data)


class UploadStatusAPIView(APIView):
    """
    Upload a new text, image, or video status.
    """

    permission_classes = (
        permissions.IsAuthenticated,
    )

    parser_classes = (
        MultiPartParser,
        FormParser,
    )

    @extend_schema(
        summary="Upload Status",
        request=OpenApiRequest(
            request=UploadStatusSerializer,
            encoding={
                "media": {
                    "contentType": "application/octet-stream",
                },
            },
        ),
        description=(
            "Upload a new image, video, or text status. "
            "Status expires after 24 hours."
        ),
        responses={
            201: StatusSerializer,
        },
        tags=["Status"],
    )
    def post(self, request):
        with transaction.atomic():
            serializer = UploadStatusSerializer(
                data=request.data,
                context={"request": request},
            )
            serializer.is_valid(raise_exception=True)
            mention_ids = serializer.validated_data.get("mentions", [])
            status_obj = serializer.save()
            transaction.on_commit(lambda: notify_status_feed_changed(request.user, "posted"))
            if mention_ids:
                transaction.on_commit(lambda: notify_status_mentioned(status_obj, mention_ids))

            return Response(
                {
                    "message": "Status uploaded successfully.",
                    "data": StatusSerializer(
                        status_obj,
                        context={"request": request},
                    ).data,
                },
                status=status.HTTP_201_CREATED,
            )


class ReportStatusAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "status_report"

    @extend_schema(
        summary="Report a status update",
        request=CreateStatusReportSerializer,
        responses={201: OpenApiResponse(description="Report submitted for moderation."), 404: OpenApiResponse(description="Status not found.")},
        tags=["Status"],
    )
    def post(self, request, pk):
        story = get_object_or_404(
            Status.objects.select_related("user"),
            pk=pk,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )
        if story.user_id == request.user.id:
            return Response({"detail": "You cannot report your own status."}, status=status.HTTP_400_BAD_REQUEST)
        from apps.chat.utils import blocked_user_ids

        blocked = blocked_user_ids(request.user.id)
        if story.user_id in blocked or SocialMute.objects.filter(muter=request.user, muted_id=story.user_id).exists():
            raise Http404
        contact_ids = status_contact_ids(request.user)
        if not can_view_status(story, request.user, contact_ids):
            raise Http404

        serializer = CreateStatusReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report, created = StatusReport.objects.get_or_create(
            status=story,
            reporter=request.user,
            defaults=serializer.validated_data,
        )
        return Response(
            {"reported": True, "already_reported": not created, "detail": "Thanks. Your report was sent for review."},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class EditStatusAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(summary="Edit a status caption or text", request=UpdateStatusContentSerializer, responses={200: StatusSerializer}, tags=["Status"])
    def patch(self, request, pk):
        story = get_object_or_404(Status, pk=pk, user=request.user, is_deleted=False, expires_at__gt=timezone.now())
        serializer = UpdateStatusContentSerializer(story, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        notify_status_feed_changed(request.user, "updated")
        return Response(StatusSerializer(story, context={"request": request}).data)


class ShareStatusToChatAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_scope = "status_share"

    @extend_schema(summary="Share a status to a chat", request=None, responses={201: OpenApiResponse(description="Status shared."), 403: OpenApiResponse(description="Chat audience cannot view this status.")}, tags=["Status"])
    def post(self, request, pk):
        story = get_object_or_404(Status.objects.select_related("user"), pk=pk, is_deleted=False, expires_at__gt=timezone.now())
        if story.user_id != request.user.id and not can_view_status(story, request.user, status_contact_ids(request.user)):
            raise Http404
        try:
            room_id = int(request.data.get("room_id"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a chat first."}, status=status.HTTP_400_BAD_REQUEST)
        room = get_object_or_404(ChatRoom, pk=room_id, is_active=True)
        from apps.chat.permissions import send_message_error
        from apps.chat.utils import sender_has_blocked_peer, blocked_user_ids, broadcast_message, get_message_with_relations

        denied = send_message_error(request.user, room)
        if denied:
            return Response({"detail": denied}, status=status.HTTP_403_FORBIDDEN)
        if sender_has_blocked_peer(room, request.user):
            return Response({"detail": "Unblock this contact to send a message."}, status=status.HTTP_403_FORBIDDEN)

        recipient_ids = list(
            Participant.objects.filter(room=room, joined_at__lte=timezone.now(), user__is_active=True, user__is_deleted=False)
            .exclude(user=request.user).values_list("user_id", flat=True).distinct()
        )
        if not recipient_ids:
            return Response({"detail": "Choose a chat with at least one other member."}, status=status.HTTP_400_BAD_REQUEST)
        blocked_by_author = blocked_user_ids(story.user_id)
        from apps.social.models import SocialMute

        for recipient_id in recipient_ids:
            recipient = User.objects.filter(pk=recipient_id, is_active=True, is_deleted=False).first()
            if recipient is None:
                return Response({"detail": "Everyone in this chat must be able to view the status."}, status=status.HTTP_403_FORBIDDEN)
            if recipient.id != story.user_id:
                if recipient.id in blocked_by_author or story.user_id in blocked_user_ids(recipient.id):
                    return Response({"detail": "Everyone in this chat must be able to view the status."}, status=status.HTTP_403_FORBIDDEN)
                if SocialMute.objects.filter(muter=recipient, muted=story.user).exists():
                    return Response({"detail": "Everyone in this chat must be able to view the status."}, status=status.HTTP_403_FORBIDDEN)
                if not can_view_status(story, recipient, status_contact_ids(recipient)):
                    return Response({"detail": "Everyone in this chat must be able to view the status."}, status=status.HTTP_403_FORBIDDEN)

        from .replies import status_snapshot

        snapshot = status_snapshot(story)
        # A shared card is a link to the live, permission-checked story. Never
        # copy an owner-bound media capability into a multi-member chat.
        snapshot["status_media"] = ""
        snapshot["status_text"] = ""
        expires_at = timezone.now() + timedelta(seconds=room.disappearing_seconds) if room.disappearing_seconds else None
        message = Message.objects.create(
            room=room,
            sender=request.user,
            message_type=MessageType.TEXT,
            content="Shared a status update",
            client_message_id=f"status-share-{story.pk}-{request.user.pk}-{uuid.uuid4().hex[:12]}",
            status_ref=snapshot,
            expires_at=expires_at,
        )
        message = get_message_with_relations(message.pk)
        broadcast_message(message, request)
        return Response({"message": "Status shared to chat.", "data": MessageSerializer(message, context={"request": request}).data}, status=status.HTTP_201_CREATED)

    

class MyStatusAPIView(generics.ListAPIView):
    """
    Return my active statuses.
    """

    serializer_class = StatusSerializer

    permission_classes = (
        permissions.IsAuthenticated,
    )

    @extend_schema(
        summary="My Status",
        responses={
            200: StatusSerializer(many=True),
        },
        tags=["Status"],
    )

    def get_queryset(self):

        return (
            Status.objects.filter(
                user=self.request.user,
                is_deleted=False,
                expires_at__gt=timezone.now(),
            ).select_related(
                "user",
                "user__profile",
            ).prefetch_related(
                "views",
                "privacy_rules",
                "mentions",
            )
            .order_by(
                "-created_at",
            )
        )
    

class ContactsStatusAPIView(APIView):
    """
    Return statuses grouped by contact, plus EVERYONE statuses.
    """

    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Contacts Status",
        responses={200: ContactStatusSerializer(many=True)},
        tags=["Status"],
    )
    
    def can_view_status(self, status_obj, user, contact_ids, saved_me_ids=None, chat_partner_ids=None):
        # Keep the existing view method contract while policy stays in domain code.
        return can_view_status(status_obj, user, contact_ids, saved_me_ids, chat_partner_ids)


    def get(self, request):
        
        contact_ids = set(
            Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True)
        )
        chat_partner_ids = set(Participant.objects.filter(
            room__room_type=RoomType.PRIVATE,
            room__is_active=True,
            room__participants__user=request.user,
        ).exclude(user=request.user).values_list("user_id", flat=True))
        contact_ids |= chat_partner_ids
        saved_me_ids = set(
            Contact.objects.filter(contact_user=request.user).values_list("owner_id", flat=True)
        )

        # Only people connected to me (saved either way or chatting) can
        # ever show up; each status is then checked against its audience.
        candidate_ids = contact_ids | saved_me_ids
        # Blocked either way: neither side sees the other's status.
        from apps.chat.utils import blocked_user_ids

        blocked = blocked_user_ids(request.user.id)
        muted_ids = set(SocialMute.objects.filter(muter=request.user).values_list("muted_id", flat=True))
        candidate_ids -= blocked | muted_ids
        contact_ids -= blocked | muted_ids

        statuses = (
            Status.objects.filter(
                user_id__in=candidate_ids,
                user__is_active=True,
                user__is_deleted=False,
                is_deleted=False,
                expires_at__gt=timezone.now(),
            )
            .select_related("user", "user__profile")
            .prefetch_related("views", "privacy_rules", "mentions")
            .order_by("user_id", "-created_at")
        )

        grouped = {}

        for status_obj in statuses:
            if not self.can_view_status(
                status_obj, request.user, contact_ids, saved_me_ids, chat_partner_ids
            ):
                continue

            user_id = status_obj.user_id

            if user_id not in grouped:
                grouped[user_id] = {
                    "user": status_obj.user,
                    "statuses": [],
                }

            grouped[user_id]["statuses"].append(status_obj)

        serializer = ContactStatusSerializer(
            grouped.values(),
            many=True,
            context={"request": request},
        )

        return Response(serializer.data)

    

class ViewStatusAPIView(APIView):
    """
    Mark a status as viewed.
    """

    permission_classes = (
        permissions.IsAuthenticated,
    )

    @extend_schema(
        summary="View Status",
        request=None,
        responses={
            200: OpenApiResponse(description="Viewed."),
        },
        tags=["Status"],
    )

    def post(
        self,
        request,
        pk,
    ):

        status_obj = get_object_or_404(
            Status,
            pk=pk,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )

        
        if status_obj.user_id == request.user.id:
            return Response(
                {"detail": "You cannot view your own status."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if SocialMute.objects.filter(muter=request.user, muted_id=status_obj.user_id).exists():
            return Response({"detail": "You muted this account's updates."}, status=status.HTTP_404_NOT_FOUND)

        contact_ids = status_contact_ids(request.user)

        if not ContactsStatusAPIView().can_view_status(
            status_obj,
            request.user,
            contact_ids,
        ):
            return Response(
                {"detail": "You are not allowed to view this status."},
                status=status.HTTP_403_FORBIDDEN,
            )

        _view, created = StatusView.objects.get_or_create(
            status=status_obj,
            viewer=request.user,
        )
        if created:
            notify_status_viewed(status_obj, request.user)

        return Response(
            {"message": "Status viewed successfully."},
            status=status.HTTP_200_OK,
        )

    
class StatusReactionAPIView(APIView):
    """React to a visible status and post that reaction into the owner's DM."""
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="React to a status",
        request=ReactToStatusSerializer,
        responses={200: OpenApiResponse(description="Reaction sent to chat.")},
        tags=["Status"],
    )
    def post(self, request, pk):
        status_obj = get_object_or_404(
            Status.objects.select_related("user"),
            pk=pk,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )
        if status_obj.user_id == request.user.id:
            return Response({"detail": "You cannot react to your own status."}, status=status.HTTP_400_BAD_REQUEST)

        if SocialMute.objects.filter(muter=request.user, muted_id=status_obj.user_id).exists():
            return Response({"detail": "You muted this account's updates."}, status=status.HTTP_404_NOT_FOUND)

        contact_ids = set(Contact.objects.filter(owner=request.user).values_list("contact_user_id", flat=True))
        contact_ids.update(
            Participant.objects.filter(
                room__room_type=RoomType.PRIVATE,
                room__is_active=True,
                room__participants__user=request.user,
            ).exclude(user=request.user).values_list("user_id", flat=True)
        )
        if not ContactsStatusAPIView().can_view_status(status_obj, request.user, contact_ids):
            return Response({"detail": "You cannot react to this status."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ReactToStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        emoji = serializer.validated_data.get("emoji") or ""
        text = serializer.validated_data.get("text") or ""

        with transaction.atomic():
            room = (
                ChatRoom.objects.filter(
                    room_type=RoomType.PRIVATE,
                    is_active=True,
                    participants__user=request.user,
                )
                .filter(participants__user=status_obj.user)
                .distinct()
                .first()
            )
            if room is None:
                room = ChatRoom.objects.create(room_type=RoomType.PRIVATE, created_by=request.user)
                Participant.objects.get_or_create(room=room, user=request.user)
                Participant.objects.get_or_create(room=room, user=status_obj.user)

            media_url = ""
            if status_obj.media:
                from .media import status_media_url
                media_url = status_media_url(status_obj, status_obj.user_id)
            preview = {
                "kind": "status_reaction",
                "status_id": status_obj.id,
                "status_type": status_obj.status_type,
                "status_text": (status_obj.content or "").strip()[:180],
                "status_media": media_url,
                "status_bg": getattr(status_obj, "background_color", "") or "",
                "status_fg": getattr(status_obj, "text_color", "") or "",
                "emoji": emoji,
                "text": text,
                "reactor_id": request.user.id,
                "owner_id": status_obj.user_id,
                "status_created_at": status_obj.created_at.isoformat(),
            }
            content = "__MHTALK_STATUS_REACTION__:" + json.dumps(preview, separators=(",", ":"))
            # Like WhatsApp, every reaction is its own chat message: reacting
            # three times to a status shows three "Reacted … to a status" cards.
            message = Message.objects.create(
                room=room,
                sender=request.user,
                client_message_id=f"status-reaction-{status_obj.id}-{request.user.id}-{uuid.uuid4().hex[:12]}",
                message_type="TEXT",
                content=content,
            )
            # The status keeps the viewer's latest reaction (shown on the status).
            reaction = None
            if emoji:
                reaction, _created_reaction = StatusReaction.objects.update_or_create(
                    status=status_obj,
                    reactor=request.user,
                    defaults={"emoji": emoji, "chat_message": message},
                )
            room.updated_at = timezone.now()
            room.save(update_fields=["updated_at"])

        from apps.chat.utils import broadcast_message, get_message_with_relations

        message = get_message_with_relations(message.id)
        broadcast_message(message, request)
        message_data = MessageSerializer(message, context={"request": request}).data
        return Response(
            {
                "message": "Status reaction sent in chat." if emoji else "Status reply sent in chat.",
                "room_id": room.id,
                "status_reaction": {"id": reaction.id, "emoji": reaction.emoji, "status_id": status_obj.id} if reaction else None,
                "chat_message": message_data,
            },
            status=status.HTTP_200_OK,
        )


class DeleteStatusAPIView(APIView):
    """
    Soft delete a status.
    """

    permission_classes = (
        permissions.IsAuthenticated,
    )

    @extend_schema(
        summary="Delete Status",
        request=None,
        responses={
            200: OpenApiResponse(description="Deleted."),
        },
        tags=["Status"],
    )

    def delete(
        self,
        request,
        pk,
    ):

        status_obj = get_object_or_404(
            Status,
            pk=pk,
            user=request.user,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )

        status_obj.is_deleted = True
        media = status_obj.media
        status_obj.save(update_fields=["is_deleted"])
        notify_status_feed_changed(request.user, "deleted")
        if media:
            transaction.on_commit(lambda: media.delete(save=False))

        return Response(
            {
                "message":
                "Status deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )
    


class UpdateStatusPrivacyAPIView(APIView):
    """Status audiences are snapshotted at publication; old updates are immutable."""
    permission_classes = (permissions.IsAuthenticated,)

    @extend_schema(
        summary="Update status privacy (unsupported for published statuses)",
        request=StatusPrivacySerializer,
        responses={400: OpenApiResponse(description="Publish a new status to change its audience.")},
        tags=["Status"],
    )
    def post(self, request, pk):
        get_object_or_404(
            Status,
            pk=pk,
            user=request.user,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )
        return Response(
            {"detail": "Status privacy applies to new updates only. Publish a new status to use a different audience; existing updates are unchanged."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class StatusViewersAPIView(generics.ListAPIView):
    """
    Return viewers of my status.
    """

    serializer_class = StatusViewSerializer

    permission_classes = (
        permissions.IsAuthenticated,
    )

    @extend_schema(
        summary="Status Viewers",
        responses={
            200: StatusViewSerializer(many=True),
        },
        tags=["Status"],
    )

    def get_queryset(self):

        status_obj = get_object_or_404(
            Status,
            pk=self.kwargs["pk"],
            user=self.request.user,
            is_deleted=False,
            expires_at__gt=timezone.now(),
        )

        return (
            StatusView.objects.filter(
                status=status_obj,
            )
            .select_related(
                "viewer",
                "viewer__profile",
            )
            .order_by(
                "-viewed_at",
            )
        )
