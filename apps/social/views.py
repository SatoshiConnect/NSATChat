import mimetypes

from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.chat.utils import blocked_user_ids
from .models import Post, PostAttachment, PostComment, PostLike, PostReport, PostSave, SocialFollow
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

    def _response(self, file_field):
        try:
            handle = file_field.open("rb")
        except (OSError, ValueError, FileNotFoundError):
            raise Http404
        response = FileResponse(handle, content_type=mimetypes.guess_type(file_field.name)[0] or "application/octet-stream")
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response

    def get(self, request, pk, attachment_id=None):
        return self._response(self._authorized_claims(request, pk, attachment_id))


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
        queryset = visible_posts_for(self.request.user)
        if self.request.query_params.get("scope") == "following":
            following_ids = SocialFollow.objects.filter(follower=self.request.user, status=SocialFollow.ACCEPTED).values("following_id")
            queryset = queryset.filter(Q(author=self.request.user) | Q(author_id__in=following_ids))
        elif self.request.query_params.get("scope") == "saved":
            queryset = queryset.filter(saves__user=self.request.user)
        return queryset.select_related("author", "author__profile").annotate(
            likes_count=Count("likes", distinct=True), comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True), distinct=True), _is_liked=Exists(liked), _is_saved=Exists(saved)
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class PostDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_throttles(self):
        self.throttle_scope = "social_interaction" if self.request.method in ("POST", "PATCH", "DELETE") else None
        return super().get_throttles()

    def post_obj(self, request, pk):
        return get_object_or_404(visible_posts_for(request.user), pk=pk)

    def post(self, request, pk):
        post = self.post_obj(request, pk)
        like, created = PostLike.objects.get_or_create(post=post, user=request.user)
        if not created:
            like.delete()
        return Response({"liked": created, "likes_count": post.likes.count()})

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


class PostCommentsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get_throttles(self):
        self.throttle_scope = "social_comment" if self.request.method == "POST" else None
        return super().get_throttles()

    def get(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        comments = post.comments.filter(deleted_at__isnull=True, parent__isnull=True).select_related("author", "author__profile")
        return Response(PostCommentSerializer(comments, many=True, context={"request": request}).data)

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        serializer = CreateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attrs = dict(serializer.validated_data)
        parent_id = attrs.pop("parent_id", None)
        parent = None
        if parent_id:
            parent = get_object_or_404(PostComment, pk=parent_id, post=post, deleted_at__isnull=True, parent__isnull=True)
        comment = PostComment.objects.create(post=post, author=request.user, parent=parent, **attrs)
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
        serializer = CreateCommentSerializer(data=request.data)
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
