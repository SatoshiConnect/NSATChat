"""Discovery and membership APIs for explicitly published OpenChat communities."""

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from .choices import RoomType
from .group_events import post_group_event
from .models import ChatRoom, CommunityJoinRequest, OpenCommunity, OpenCommunityReport, Participant
from .permissions import is_group_admin
from .utils import broadcast_room_changed


def _community_data(community, user):
    room = community.room
    member_count = getattr(community, "_member_count", None)
    is_member = getattr(community, "_is_member", None)
    if member_count is None:
        member_count = Participant.objects.filter(room=room).count()
    if is_member is None:
        is_member = Participant.objects.filter(room=room, user=user).exists()
    return {
        "id": community.pk,
        "room_id": room.pk,
        "name": room.name,
        "description": room.description,
        "photo": room.photo.url if room.photo else None,
        "category": community.category,
        "category_label": community.get_category_display(),
        "tags": community.tags,
        "guidelines": community.guidelines,
        "join_mode": community.join_mode,
        "state": community.state,
        "searchable": community.searchable,
        "preview_enabled": community.preview_enabled,
        "member_count": member_count,
        "is_member": is_member,
        "is_owner": community.owner_id == user.pk,
        "is_admin": getattr(community, "_is_admin", None) if getattr(community, "_is_admin", None) is not None else is_group_admin(user, room),
        "has_pending_request": getattr(community, "_has_pending_request", False),
        "created_at": community.created_at,
        "published_at": community.published_at,
    }


def _display_name(user, proposed):
    name = str(proposed or "").strip()
    if not name or name == user.phone_number or name == user.email:
        name = "Member"
    return name[:50]


class OpenCommunityCatalogAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_read"

    def get(self, request):
        query = str(request.query_params.get("q") or "").strip()[:80]
        category = str(request.query_params.get("category") or "").strip().upper()
        mine = request.query_params.get("mine") == "1"
        if mine:
            communities = OpenCommunity.objects.filter(
                Q(room__participants__user=request.user)
                | Q(owner=request.user)
                | Q(join_requests__user=request.user, join_requests__state=CommunityJoinRequest.State.PENDING)
            ).select_related("room", "owner").distinct()
        else:
            communities = OpenCommunity.objects.filter(
                state=OpenCommunity.State.PUBLISHED,
                searchable=True,
                room__is_active=True,
            ).select_related("room", "owner")
        if category in dict(OpenCommunity.CATEGORY_CHOICES):
            communities = communities.filter(category=category)
        if query:
            communities = communities.filter(Q(room__name__icontains=query) | Q(room__description__icontains=query))
        try:
            limit = min(max(int(request.query_params.get("limit", 20)), 1), 30)
            offset = max(int(request.query_params.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return Response({"detail": "Invalid pagination."}, status=status.HTTP_400_BAD_REQUEST)
        total = communities.count()
        page = communities.annotate(
            _member_count=Count("room__participants", distinct=True),
            _is_member=Exists(Participant.objects.filter(room_id=OuterRef("room_id"), user=request.user)),
            _is_admin=Exists(Participant.objects.filter(room_id=OuterRef("room_id"), user=request.user, is_admin=True)),
            _has_pending_request=Exists(CommunityJoinRequest.objects.filter(community_id=OuterRef("pk"), user=request.user, state=CommunityJoinRequest.State.PENDING)),
        ).order_by("-published_at", "-id")[offset:offset + limit]
        return Response({
            "count": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "results": [_community_data(community, request.user) for community in page],
        })


class OpenCommunityCreateAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser, FormParser, MultiPartParser)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_create"

    def post(self, request):
        name = str(request.data.get("name") or "").strip()
        description = str(request.data.get("description") or "").strip()
        category = str(request.data.get("category") or "OTHER").strip().upper()
        join_mode = str(request.data.get("join_mode") or "OPEN").strip().upper()
        guidelines = str(request.data.get("guidelines") or "").strip()
        display_name = _display_name(request.user, request.data.get("display_name"))
        if not name or len(name) > 80:
            return Response({"name": ["Enter a community name (80 characters or fewer)."]}, status=status.HTTP_400_BAD_REQUEST)
        if not description or len(description) > 255:
            return Response({"description": ["Enter a short description (255 characters or fewer)."]}, status=status.HTTP_400_BAD_REQUEST)
        if category not in dict(OpenCommunity.CATEGORY_CHOICES):
            return Response({"category": ["Choose a valid category."]}, status=status.HTTP_400_BAD_REQUEST)
        if join_mode not in OpenCommunity.JoinMode.values:
            return Response({"join_mode": ["Choose open, code, or approval access."]}, status=status.HTTP_400_BAD_REQUEST)
        if len(guidelines) > 3000:
            return Response({"guidelines": ["Guidelines must be 3,000 characters or fewer."]}, status=status.HTTP_400_BAD_REQUEST)
        join_code = str(request.data.get("join_code") or "").strip()
        if join_mode == OpenCommunity.JoinMode.CODE and not 4 <= len(join_code) <= 32:
            return Response({"join_code": ["Use a community-specific code between 4 and 32 characters."]}, status=status.HTTP_400_BAD_REQUEST)
        raw_tags = request.data.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split(",")
        if not isinstance(raw_tags, (list, tuple)):
            return Response({"tags": ["Tags must be a list of text values."]}, status=status.HTTP_400_BAD_REQUEST)
        tags = list(dict.fromkeys(str(tag).strip().lstrip("#")[:24] for tag in raw_tags if str(tag).strip()))[:10]
        def parse_bool(value, default=True):
            if value is None:
                return default
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return value != 0
            return str(value).strip().lower() not in ("false", "0", "no", "off", "")

        photo = request.FILES.get("photo")
        if photo:
            if photo.size > 5 * 1024 * 1024:
                return Response({"photo": ["Upload an image of 5 MB or smaller."]}, status=status.HTTP_400_BAD_REQUEST)
            try:
                image = Image.open(photo)
                if (
                    image.format not in {"JPEG", "PNG", "WEBP"}
                    or image.width > 8192
                    or image.height > 8192
                    or image.width * image.height > 25_000_000
                ):
                    raise ValueError("Unsupported image dimensions or format.")
                image.verify()
            except (UnidentifiedImageError, OSError, ValueError):
                return Response({"photo": ["Upload a valid JPEG, PNG, or WebP image up to 8192 pixels per side."]}, status=status.HTTP_400_BAD_REQUEST)
            finally:
                photo.seek(0)
        with transaction.atomic():
            room = ChatRoom.objects.create(
                name=name,
                description=description,
                photo=photo,
                room_type=RoomType.GROUP,
                created_by=request.user,
            )
            Participant.objects.create(room=room, user=request.user, is_admin=True, community_display_name=display_name)
            community = OpenCommunity.objects.create(
                room=room,
                owner=request.user,
                category=category,
                join_mode=join_mode,
                searchable=parse_bool(request.data.get("searchable")),
                preview_enabled=parse_bool(request.data.get("preview_enabled")),
                guidelines=guidelines,
                tags=tags,
                join_code_hash=make_password(join_code) if join_mode == OpenCommunity.JoinMode.CODE else "",
            )
        broadcast_room_changed(room.pk, "created")
        return Response(_community_data(community, request.user), status=status.HTTP_201_CREATED)


class OpenCommunityDetailAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_read"

    def get(self, request, pk):
        community = get_object_or_404(OpenCommunity.objects.select_related("room", "owner"), pk=pk)
        if community.state != OpenCommunity.State.PUBLISHED and community.owner_id != request.user.pk and not is_group_admin(request.user, community.room):
            return Response({"detail": "Community not found."}, status=status.HTTP_404_NOT_FOUND)
        data = _community_data(community, request.user)
        if not community.preview_enabled and not data["is_member"] and not data["is_owner"]:
            data["description"] = ""
            data["guidelines"] = ""
            data["tags"] = []
        return Response(data)


class OpenCommunityJoinAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_join"

    def post(self, request, pk):
        community = get_object_or_404(OpenCommunity.objects.select_related("room", "owner"), pk=pk, state=OpenCommunity.State.PUBLISHED, room__is_active=True)
        if Participant.objects.filter(room=community.room, user=request.user).exists():
            return Response({"state": "JOINED", "room_id": community.room_id})
        display_name = _display_name(request.user, request.data.get("display_name"))
        if community.join_mode == OpenCommunity.JoinMode.CODE:
            code = str(request.data.get("join_code") or "").strip()
            if not code or not check_password(code, community.join_code_hash):
                return Response({"detail": "That community code is not valid."}, status=status.HTTP_400_BAD_REQUEST)
        if community.join_mode == OpenCommunity.JoinMode.APPROVAL:
            answer = str(request.data.get("answer") or "").strip()
            if len(answer) > 500:
                return Response({"answer": ["Answer must be 500 characters or fewer."]}, status=status.HTTP_400_BAD_REQUEST)
            join_request, _ = CommunityJoinRequest.objects.update_or_create(
                community=community,
                user=request.user,
                defaults={"display_name": display_name, "answer": answer, "state": CommunityJoinRequest.State.PENDING, "reviewed_by": None, "reviewed_at": None},
            )
            return Response({"state": "PENDING", "request_id": join_request.pk}, status=status.HTTP_202_ACCEPTED)
        with transaction.atomic():
            Participant.objects.get_or_create(room=community.room, user=request.user, defaults={"community_display_name": display_name})
        post_group_event(community.room, request.user, "joined_community", "{actor} joined the community", request=request)
        broadcast_room_changed(community.room_id, "participant_added")
        return Response({"state": "JOINED", "room_id": community.room_id})


class OpenCommunityJoinRequestsAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_read"

    def get(self, request, pk):
        community = get_object_or_404(OpenCommunity.objects.select_related("room"), pk=pk)
        if not is_group_admin(request.user, community.room):
            return Response({"detail": "Only community admins can review join requests."}, status=status.HTTP_403_FORBIDDEN)
        requests = community.join_requests.filter(state=CommunityJoinRequest.State.PENDING).select_related("user")[:100]
        return Response([{
            "id": item.pk,
            "display_name": item.display_name,
            "answer": item.answer,
            "created_at": item.created_at,
        } for item in requests])

    def post(self, request, pk):
        community = get_object_or_404(OpenCommunity.objects.select_related("room"), pk=pk)
        if not is_group_admin(request.user, community.room):
            return Response({"detail": "Only community admins can review join requests."}, status=status.HTTP_403_FORBIDDEN)
        try:
            request_id = int(request.data.get("request_id"))
        except (TypeError, ValueError):
            return Response({"request_id": ["A valid request ID is required."]}, status=status.HTTP_400_BAD_REQUEST)
        decision = str(request.data.get("decision") or "").upper()
        if decision not in ("APPROVED", "REJECTED"):
            return Response({"decision": ["Choose APPROVED or REJECTED."]}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            join_request = get_object_or_404(
                CommunityJoinRequest.objects.select_for_update(),
                pk=request_id,
                community=community,
                state=CommunityJoinRequest.State.PENDING,
            )
            join_request.state = decision
            join_request.reviewed_by = request.user
            join_request.reviewed_at = timezone.now()
            join_request.save(update_fields=("state", "reviewed_by", "reviewed_at"))
            if decision == "APPROVED":
                Participant.objects.get_or_create(room=community.room, user=join_request.user, defaults={"community_display_name": join_request.display_name})
        if decision == "APPROVED":
            post_group_event(community.room, join_request.user, "joined_community", "{actor} joined the community", request=request)
            broadcast_room_changed(community.room_id, "participant_added")
        return Response({"state": join_request.state, "room_id": community.room_id if decision == "APPROVED" else None})


class OpenCommunityReportAPIView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "openchat_report"

    def post(self, request, pk):
        community = get_object_or_404(OpenCommunity, pk=pk, state=OpenCommunity.State.PUBLISHED)
        if community.owner_id == request.user.pk:
            return Response({"detail": "You cannot report your own community."}, status=status.HTTP_400_BAD_REQUEST)
        reason = str(request.data.get("reason") or "OTHER").upper()
        if reason not in OpenCommunityReport.Reason.values:
            return Response({"reason": ["Choose a valid report reason."]}, status=status.HTTP_400_BAD_REQUEST)
        details = str(request.data.get("details") or "").strip()
        if len(details) > 1000:
            return Response({"details": ["Details must be 1,000 characters or fewer."]}, status=status.HTTP_400_BAD_REQUEST)
        report, created = OpenCommunityReport.objects.get_or_create(
            community=community,
            reporter=request.user,
            defaults={"reason": reason, "details": details},
        )
        return Response({"reported": True, "already_reported": not created, "state": report.state}, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
