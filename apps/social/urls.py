from django.urls import path
from .views import PostCommentsAPIView, PostDetailAPIView, PostFeedAPIView, PostReportAPIView

app_name = "social"
urlpatterns = [
    path("posts/", PostFeedAPIView.as_view(), name="post-feed"),
    path("posts/<int:pk>/", PostDetailAPIView.as_view(), name="post-detail"),
    path("posts/<int:pk>/comments/", PostCommentsAPIView.as_view(), name="post-comments"),
    path("posts/<int:pk>/report/", PostReportAPIView.as_view(), name="post-report"),
]
