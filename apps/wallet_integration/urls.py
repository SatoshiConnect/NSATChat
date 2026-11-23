from django.urls import path

from .views import (
    WalletLinkConfirmAPIView,
    WalletLinkMeAPIView,
    WalletLinkStartAPIView,
    WalletChatRecipientAPIView,
    WalletReadAPIView,
)


app_name = "wallet_integration"

urlpatterns = [
    path("read/", WalletReadAPIView.as_view(), name="read"),
    path("link/start/", WalletLinkStartAPIView.as_view(), name="link-start"),
    path("link/confirm/", WalletLinkConfirmAPIView.as_view(), name="link-confirm"),
    path("link/me/", WalletLinkMeAPIView.as_view(), name="link-me"),
    path("chat/recipient/", WalletChatRecipientAPIView.as_view(), name="chat-recipient"),
]
