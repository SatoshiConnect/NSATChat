from django.urls import path

from .views import TodayNewsFeedAPIView

app_name = "news"
urlpatterns = [path("today/", TodayNewsFeedAPIView.as_view(), name="today-feed")]
