from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Post, PostComment, PostLike
from .policies import can_view_post, visible_posts_for
from .serializers import CreateCommentSerializer, PostCommentSerializer, PostSerializer


class SocialPostPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 50


class PostFeedAPIView(generics.ListCreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    parser_classes = (JSONParser, MultiPartParser, FormParser)
    serializer_class = PostSerializer
    pagination_class = SocialPostPagination

    def get_queryset(self):
        liked = PostLike.objects.filter(post_id=OuterRef("pk"), user=self.request.user)
        return visible_posts_for(self.request.user).select_related("author", "author__profile").annotate(
            likes_count=Count("likes", distinct=True), comments_count=Count("comments", filter=Q(comments__deleted_at__isnull=True), distinct=True), _is_liked=Exists(liked)
        )

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)


class PostDetailAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

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


class PostCommentsAPIView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        comments = post.comments.filter(deleted_at__isnull=True).select_related("author", "author__profile")
        return Response(PostCommentSerializer(comments, many=True, context={"request": request}).data)

    def post(self, request, pk):
        post = get_object_or_404(visible_posts_for(request.user), pk=pk)
        serializer = CreateCommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = PostComment.objects.create(post=post, author=request.user, **serializer.validated_data)
        return Response(PostCommentSerializer(comment, context={"request": request}).data, status=status.HTTP_201_CREATED)
