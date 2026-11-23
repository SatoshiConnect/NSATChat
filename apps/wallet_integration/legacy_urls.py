from django.urls import path

from .views import WalletReadAPIView


urlpatterns = [
    path("", WalletReadAPIView.as_view(), name="legacy-wallet-read"),
]
