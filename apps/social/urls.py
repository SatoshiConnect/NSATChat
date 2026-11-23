from django.urls import path
from .views import PostCommentDetailAPIView, PostCommentsAPIView, PostDetailAPIView, PostFeedAPIView, PostReportAPIView

app_name = "social"
urlpatterns = [
    path("posts/", PostFeedAPIView.as_view(), name="post-feed"),
    path("posts/<int:pk>/", PostDetailAPIView.as_view(), name="post-detail"),
    path("posts/<int:pk>/comments/", PostCommentsAPIView.as_view(), name="post-comments"),
    path("posts/<int:post_pk>/comments/<int:comment_pk>/", PostCommentDetailAPIView.as_view(), name="post-comment-detail"),
    path("posts/<int:pk>/report/", PostReportAPIView.as_view(), name="post-report"),
]
