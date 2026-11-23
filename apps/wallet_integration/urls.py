from django.urls import path

from .views import WalletReadAPIView


app_name = "wallet_integration"

urlpatterns = [
    path("read/", WalletReadAPIView.as_view(), name="read"),
]
